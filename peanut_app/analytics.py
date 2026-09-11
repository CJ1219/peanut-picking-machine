from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .database import ProductionDatabase


class AnalyticsService:
    def __init__(self, database: ProductionDatabase):
        self.database = database

    @staticmethod
    def report_sections(report: str) -> tuple[str, str]:
        """Separate the model's summary from its full explanation without clipping text."""
        if "【簡述】" in report and "【詳細說明】" in report:
            before, detail = report.split("【詳細說明】", 1)
            if "【簡述】" in before:
                brief = before.split("【簡述】", 1)[1].strip()
                if brief and detail.strip():
                    return brief, detail.strip()
        return "此份內容未提供獨立摘要，請查看「詳細說明」。", report

    def deterministic_report(self) -> str:
        rows = self.database.summary_rows()
        if not rows:
            return "目前沒有可分析的生產資料。"

        lines = [
            "生產資料統計（由 SQLite/Python 計算，非語言模型自行估算）：",
            "",
        ]
        for row in rows:
            total = int(row["total"] or 0)
            ng = int(row["ng"] or 0)
            ng_rate = ng / total * 100.0 if total else 0.0
            avg_confidence = row["avg_confidence"]
            confidence_text = (
                f"{float(avg_confidence) * 100:.1f}%"
                if avg_confidence is not None
                else "無資料"
            )
            lines.append(
                f"- {row['production_month']}｜廠商 {row['vendor_code']} "
                f"｜種類 {row['variety_code']}｜"
                f"樣本 {total}｜NG {ng_rate:.1f}% ({ng}/{total})｜"
                f"平均信心 {confidence_text}"
            )

        lines.extend(
            [
                "",
                "注意：樣本數過少時不可直接判定廠商品質或季節差異；",
                "模型是否變好必須使用固定驗證集的 precision、recall、mAP 等指標。",
            ]
        )
        model_rows = self.database.model_version_rows()
        if model_rows:
            lines.extend(["", "候選模型評估紀錄："])
            for model_row in model_rows:
                metrics = json.loads(model_row["metrics_json"] or "{}")
                metric_text = ", ".join(
                    f"{name}={float(value):.4f}" for name, value in metrics.items()
                ) or "尚無驗證指標"
                state = "正式使用中" if model_row["is_active"] else "候選、未啟用"
                lines.append(f"- {model_row['version']}｜{state}｜{metric_text}")
        return "\n".join(lines)

    def qwen_report(
        self,
        endpoint: str,
        model: str,
        timeout_seconds: int = 300,
        num_predict: int = 4096,
    ) -> str:
        hostname = (urlparse(endpoint).hostname or "").lower()
        if hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "基於本機限定規則，Qwen 只允許連線 127.0.0.1／localhost，禁止區網位址"
            )
        statistics = self.deterministic_report()
        prompt = (
            "你是花生生產資料分析助手。以下數字已由程式計算，請勿自行改動數字或"
            "虛構因果關係。請用繁體中文整理：1.可觀察趨勢 2.風險 3.需要更多資料的"
            "地方 4.後續行動。任何廠商或季節比較都必須提到樣本數。\n\n"
            "先只撰寫詳細分析，展開上述四節，解釋數據依據、樣本限制與具體行動。"
            "每節最多兩個重點，全文以 800 個中文字內為目標。"
            "請完整輸出，不要在中途省略；最後一行必須寫【分析完成】。\n\n"
            f"{statistics}"
        )
        body = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "options": {
                    "num_predict": num_predict,
                    "temperature": 0.2,
                },
            }
        # A capped response can end mid-sentence even when stream=False.
        # Retry once with more room, replacing rather than appending the draft.
        for attempt in range(2):
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"無法連線本地 Qwen 服務：{exc}") from exc
            answer = str(payload.get("response", "")).strip()
            if not answer:
                raise RuntimeError("Qwen 服務沒有回傳分析內容")
            if (payload.get("done_reason") != "length"
                    and answer.endswith("【分析完成】")):
                return self._summarize_report(endpoint, model, answer, timeout_seconds)
            if attempt == 0:
                body["options"]["num_predict"] = min(8192, max(4096, num_predict * 2))
        return answer.removesuffix("【分析完成】").rstrip() + (
            "\n\n【分析未完成：已自動重試一次，仍未收到完整結尾；以上內容僅供參考。】"
        )

    @staticmethod
    def _summarize_report(endpoint: str, model: str, detail: str, timeout_seconds: int) -> str:
        body = {
            "model": model,
            "prompt": (
                "請從下列已完成的詳細分析挑選重點，生成繁體中文簡述。"
                "只寫三個短條目：現況、主要風險、建議行動，合計約 120 字。"
                "不要重新分析或新增結論，不要更改數字，保留樣本不足等限制，"
                "省略完整模型版本名稱及逐項指標。最後一行寫【摘要完成】。\n\n"
                f"詳細分析：\n{detail}"
            ),
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {"num_predict": 2048, "temperature": 0.2},
        }
        request = urllib.request.Request(
            endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            summary = str(payload.get("response", "")).strip()
            if payload.get("done_reason") == "length" or not summary.endswith("【摘要完成】"):
                raise ValueError("未收到完整摘要")
            summary = summary.removesuffix("【摘要完成】").strip()
            if not summary:
                raise ValueError("摘要內容為空")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            summary = f"簡述生成失敗：{exc}。詳細分析已保留，請查看「詳細說明」。"
        return f"【簡述】\n{summary}\n\n【詳細說明】\n{detail}"
