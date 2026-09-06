from __future__ import annotations

import queue
import json
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from .analytics import AnalyticsService
from .barcode import BarcodeDecoder
from .config import AppConfig
from .database import ProductionDatabase
from .detection import DetectionWorker
from .domain import MachineState, PeanutRecord, ProductionStats, Severity, WorkerEvent, WorkOrderInput
from .training import TrainingPipeline
from .weight import WeightCalibration
from .model_registry import file_hash


BG = "#111827"
PANEL = "#1f2937"
PANEL_LIGHT = "#273449"
TEXT = "#f3f4f6"
MUTED = "#9ca3af"
GREEN = "#22c55e"
RED = "#ef4444"
YELLOW = "#f59e0b"
BLUE = "#3b82f6"


class PeanutProductionApp(tk.Tk):
    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config_data = config or AppConfig()
        self.config_data.ensure_directories()
        self.database = ProductionDatabase(self.config_data.database_path)
        self.database.ensure_initial_model(
            self.config_data.model_version,
            self.config_data.model_path,
            file_hash(self.config_data.model_path),
        )
        self.current_work_order = self.database.latest_work_order()
        self.worker: DetectionWorker | None = None
        self.worker_events: queue.Queue[WorkerEvent] = queue.Queue()
        self.machine_state = MachineState.STOPPED
        self.video_photo: ImageTk.PhotoImage | None = None

        self.title("花生 AI 辨識與生產管理")
        self.geometry("1380x820")
        self.minsize(1180, 720)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_style()
        self._build_variables()
        self._build_layout()
        self._refresh_work_order()
        self._refresh_stats()
        if self.current_work_order and self.database.has_active_critical_anomaly(
            self.current_work_order.id
        ):
            self._set_state(MachineState.FAULT)
        self.after(30, self._poll_worker_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", font=("Microsoft JhengHei UI", 11), padding=(12, 8))
        style.configure("Treeview", font=("Microsoft JhengHei UI", 10), rowheight=28)
        style.configure("Treeview.Heading", font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("TLabel", font=("Microsoft JhengHei UI", 10))
        style.configure("TEntry", font=("Microsoft JhengHei UI", 10))
        style.configure("TCombobox", font=("Microsoft JhengHei UI", 10))

    def _build_variables(self) -> None:
        self.state_var = tk.StringVar(value="停止")
        self.status_var = tk.StringVar(value="請先建立或確認生產工單")
        self.work_order_var = tk.StringVar(value="尚未設定")
        self.video_path_var = tk.StringVar(value=str(self.config_data.video_path))
        self.last_peanut_var = tk.StringVar(value="尚無辨識資料")
        self.normal_var = tk.StringVar(value="0\n0.0%")
        self.mold_var = tk.StringVar(value="0\n0.0%")
        self.small_var = tk.StringVar(value="0\n0.0%")
        self.unknown_var = tk.StringVar(value="0")
        self.weight_var = tk.StringVar(value="待校正")
        self.false_reject_var = tk.StringVar(value="0\n0.0%")

    def _build_layout(self) -> None:
        header = tk.Frame(self, bg=BG, padx=20, pady=14)
        header.pack(fill="x")
        tk.Label(
            header,
            text="花生 AI 辨識與生產管理",
            bg=BG,
            fg=TEXT,
            font=("Microsoft JhengHei UI", 20, "bold"),
        ).pack(side="left")
        self.state_badge = tk.Label(
            header,
            textvariable=self.state_var,
            bg=RED,
            fg="white",
            padx=18,
            pady=7,
            font=("Microsoft JhengHei UI", 11, "bold"),
        )
        self.state_badge.pack(side="right")

        info_bar = tk.Frame(self, bg=PANEL, padx=16, pady=10)
        info_bar.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(info_bar, text="目前工單：", bg=PANEL, fg=MUTED).pack(side="left")
        tk.Label(
            info_bar,
            textvariable=self.work_order_var,
            bg=PANEL,
            fg=TEXT,
            font=("Microsoft JhengHei UI", 11, "bold"),
        ).pack(side="left")
        tk.Label(info_bar, text="影片：", bg=PANEL, fg=MUTED).pack(side="left", padx=(28, 4))
        ttk.Entry(info_bar, textvariable=self.video_path_var, width=62).pack(side="left", fill="x", expand=True)
        ttk.Button(info_bar, text="選擇影片", command=self._choose_video).pack(side="left", padx=(8, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=20)
        body.grid_columnconfigure(0, weight=4)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        video_panel = tk.Frame(body, bg="black", highlightbackground="#374151", highlightthickness=1)
        video_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.video_label = tk.Label(
            video_panel,
            text="辨識畫面",
            bg="black",
            fg=MUTED,
            font=("Microsoft JhengHei UI", 16),
        )
        self.video_label.pack(fill="both", expand=True)

        side = tk.Frame(body, bg=BG)
        side.grid(row=0, column=1, sticky="nsew")
        stats_grid = tk.Frame(side, bg=BG)
        stats_grid.pack(fill="x")
        for column in range(2):
            stats_grid.grid_columnconfigure(column, weight=1)
        self._stat_card(stats_grid, 0, 0, "NORMAL", self.normal_var, GREEN)
        self._stat_card(stats_grid, 0, 1, "MOLD", self.mold_var, RED)
        self._stat_card(stats_grid, 1, 0, "SMALL", self.small_var, YELLOW)
        self._stat_card(stats_grid, 1, 1, "UNKNOWN", self.unknown_var, MUTED)
        self._stat_card(stats_grid, 2, 0, "累計估算重量", self.weight_var, BLUE)
        self._stat_card(stats_grid, 2, 1, "預估誤排除", self.false_reject_var, "#c084fc")

        details = tk.Frame(side, bg=PANEL, padx=15, pady=14)
        details.pack(fill="both", expand=True, pady=(12, 0))
        tk.Label(
            details,
            text="最近一顆",
            bg=PANEL,
            fg=TEXT,
            font=("Microsoft JhengHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            details,
            textvariable=self.last_peanut_var,
            justify="left",
            anchor="nw",
            wraplength=350,
            bg=PANEL,
            fg=MUTED,
            font=("Consolas", 10),
        ).pack(fill="both", expand=True, pady=(10, 0))

        controls = tk.Frame(self, bg=BG, padx=20, pady=14)
        controls.pack(fill="x")
        ttk.Button(controls, text="開始", command=self._start_detection).pack(side="left")
        self.pause_button = ttk.Button(controls, text="暫停", command=self._toggle_pause)
        self.pause_button.pack(side="left", padx=8)
        ttk.Button(controls, text="停止", command=self._stop_detection).pack(side="left")
        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=14)
        ttk.Button(controls, text="生產設定", command=self._open_production_settings).pack(side="left")
        ttk.Button(controls, text="異常狀況", command=self._open_anomalies).pack(side="left", padx=8)
        ttk.Button(controls, text="AI 更新", command=self._open_ai_update).pack(side="left")

        status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            bg="#0b1220",
            fg=MUTED,
            anchor="w",
            padx=20,
            pady=7,
            font=("Microsoft JhengHei UI", 9),
        )
        status_bar.pack(fill="x", side="bottom")

    @staticmethod
    def _stat_card(parent, row, column, title, variable, accent) -> None:
        card = tk.Frame(parent, bg=PANEL_LIGHT, padx=14, pady=12)
        card.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
        tk.Label(
            card,
            text=title,
            bg=PANEL_LIGHT,
            fg=MUTED,
            font=("Microsoft JhengHei UI", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            card,
            textvariable=variable,
            bg=PANEL_LIGHT,
            fg=accent,
            justify="left",
            font=("Microsoft JhengHei UI", 17, "bold"),
        ).pack(anchor="w", pady=(5, 0))

    def _choose_video(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            messagebox.showwarning("辨識進行中", "請先停止辨識再更換影片。", parent=self)
            return
        selected = filedialog.askopenfilename(
            title="選擇辨識影片",
            initialdir=str(self.config_data.video_path.parent),
            filetypes=[("影片", "*.mp4 *.avi *.mov *.mkv"), ("所有檔案", "*.*")],
        )
        if selected:
            self.video_path_var.set(selected)

    def _open_production_settings(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            messagebox.showwarning("辨識進行中", "請先停止辨識再建立新工單。", parent=self)
            return
        ProductionSettingsDialog(
            self,
            self.database,
            self.current_work_order,
            on_saved=self._on_work_order_saved,
        )

    def _on_work_order_saved(self, work_order) -> None:
        self.current_work_order = work_order
        self._set_state(MachineState.STOPPED)
        self._refresh_work_order()
        self._refresh_stats()
        self.status_var.set(f"工單 {work_order.work_order_no} 已建立，可以開始影片辨識")

    def _open_anomalies(self) -> None:
        AnomalyDialog(
            self,
            self.database,
            self.current_work_order.id if self.current_work_order else None,
            on_changed=self._after_anomaly_changed,
        )

    def _after_anomaly_changed(self) -> None:
        if self.machine_state == MachineState.FAULT and not self.database.has_active_critical_anomaly(
            self.current_work_order.id if self.current_work_order else None
        ):
            self._set_state(MachineState.STOPPED)

    def _open_ai_update(self) -> None:
        AIUpdateDialog(
            self,
            self.config_data,
            self.database,
            detection_running=bool(self.worker and self.worker.is_alive()),
        )

    def _start_detection(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if self.machine_state == MachineState.PAUSED:
                self.worker.resume()
                self._set_state(MachineState.RUNNING)
                self.pause_button.configure(text="暫停")
            return

        if self.current_work_order is None:
            self.database.add_anomaly(
                code="MISSING_PRODUCTION_DATA",
                message="尚未填入生產資料，無法開始辨識",
                severity=Severity.WARNING,
            )
            self._set_state(MachineState.FAULT)
            messagebox.showwarning("缺少生產資料", "請先進入「生產設定」建立工單。", parent=self)
            return

        if self.database.has_active_critical_anomaly(self.current_work_order.id):
            self._set_state(MachineState.FAULT)
            messagebox.showwarning("異常尚未清除", "請先至「異常狀況」清除嚴重異常。", parent=self)
            return

        calibration = WeightCalibration.load(self.config_data.calibration_path)
        stats = self.database.stats(self.current_work_order.id)
        if calibration.enabled and stats.total_weight_g >= self.current_work_order.target_weight_g:
            self.database.add_anomaly(
                code="TARGET_WEIGHT_REACHED",
                message=(
                    f"此工單已達目標重量：{stats.total_weight_g:.2f} g / "
                    f"{self.current_work_order.target_weight_g:.2f} g"
                ),
                severity=Severity.CRITICAL,
                work_order_id=self.current_work_order.id,
            )
            self._set_state(MachineState.FAULT)
            messagebox.showwarning("已達目標重量", "同一工單重新啟動後立即再次停止。", parent=self)
            return

        source_path = Path(self.video_path_var.get().strip())
        if not source_path.exists():
            messagebox.showerror("影片不存在", f"找不到影片：\n{source_path}", parent=self)
            return

        self.worker = DetectionWorker(
            config=self.config_data,
            database=self.database,
            work_order=self.current_work_order,
            video_source=source_path,
            event_queue=self.worker_events,
        )
        self.worker.start()
        self._set_state(MachineState.RUNNING)
        self.status_var.set("辨識工作已啟動，正在載入模型……")

    def _toggle_pause(self) -> None:
        if self.worker is None or not self.worker.is_alive():
            return
        if self.machine_state == MachineState.PAUSED:
            self.worker.resume()
            self._set_state(MachineState.RUNNING)
            self.pause_button.configure(text="暫停")
            self.status_var.set("辨識已繼續")
        else:
            self.worker.pause()
            self._set_state(MachineState.PAUSED)
            self.pause_button.configure(text="繼續")
            self.status_var.set("辨識已暫停")

    def _stop_detection(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.worker.stop()
            self.status_var.set("正在停止 Python 辨識……")
        else:
            self._set_state(MachineState.STOPPED)

    def _poll_worker_events(self) -> None:
        latest_frame = None
        try:
            while True:
                event = self.worker_events.get_nowait()
                if event.kind == "frame":
                    latest_frame = event.payload
                else:
                    self._handle_worker_event(event)
        except queue.Empty:
            pass
        if latest_frame is not None:
            self._display_frame(latest_frame)
        self.after(30, self._poll_worker_events)

    def _handle_worker_event(self, event: WorkerEvent) -> None:
        if event.kind == "status":
            self.status_var.set(str(event.payload))
        elif event.kind == "started":
            values = event.payload
            self._set_state(MachineState.RUNNING)
            self.status_var.set(
                f"辨識中｜來源 {values['width']}×{values['height']}｜{values['fps']:.2f} FPS"
            )
        elif event.kind == "peanut":
            self._show_last_peanut(event.payload)
        elif event.kind == "stats":
            self._apply_stats(event.payload)
        elif event.kind == "false_reject":
            self.status_var.set(f"第 {event.payload.sequence_no} 顆 normal 被標記為預估誤排")
            self._refresh_stats()
        elif event.kind == "target_reached":
            self._set_state(MachineState.FAULT)
            self._apply_stats(event.payload["stats"])
            messagebox.showwarning("已達目標重量", "Python 辨識已立即停止，異常已鎖定。", parent=self)
        elif event.kind == "video_finished":
            self.status_var.set("影片播放與辨識完成")
        elif event.kind == "stopped":
            if self.machine_state != MachineState.FAULT:
                self._set_state(MachineState.STOPPED)
            self.pause_button.configure(text="暫停")
        elif event.kind == "error":
            self._set_state(MachineState.FAULT)
            self.status_var.set(event.payload["message"])
            messagebox.showerror("Python 辨識錯誤", event.payload["message"], parent=self)

    def _display_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        available_width = max(320, self.video_label.winfo_width())
        available_height = max(240, self.video_label.winfo_height())
        image.thumbnail((available_width, available_height), Image.Resampling.LANCZOS)
        self.video_photo = ImageTk.PhotoImage(image=image)
        self.video_label.configure(image=self.video_photo, text="")

    def _show_last_peanut(self, record: PeanutRecord) -> None:
        boundary = (
            f"{record.boundary_between[0]}-{record.boundary_between[1]}"
            if record.boundary_between
            else "否"
        )
        weight = f"{record.weight_est_g:.3f} g" if record.weight_est_g is not None else "待校正"
        self.last_peanut_var.set(
            f"序號：P{record.sequence_no:06d}\n"
            f"紀錄狀態：{record.record_status}\n"
            f"類別：{record.classification.upper()}\n"
            f"中央信心：{record.confidence_center:.3f}\n"
            f"7 幀平均信心：{record.confidence_mean:.3f}\n"
            f"有效幀：{record.valid_frames}/7\n"
            f"平均面積：{record.area_mean_px2:.1f} px²\n"
            f"估算重量：{weight}\n"
            f"道別：{record.lane}\n"
            f"邊界區：{boundary}\n"
            f"預定撥片：{record.eject_lanes or '無'}\n"
            f"模型：{record.model_version}"
        )

    def _refresh_work_order(self) -> None:
        if self.current_work_order is None:
            self.work_order_var.set("尚未設定")
            return
        self.work_order_var.set(
            f"{self.current_work_order.work_order_no}｜"
            f"廠商 {self.current_work_order.vendor_code}｜批號 {self.current_work_order.material_lot}"
        )

    def _refresh_stats(self) -> None:
        if self.current_work_order is None:
            self._apply_stats(ProductionStats())
        else:
            self._apply_stats(self.database.stats(self.current_work_order.id))

    def _apply_stats(self, stats: ProductionStats) -> None:
        self.normal_var.set(f"{stats.normal}\n{stats.percentage('normal'):.1f}%")
        self.mold_var.set(f"{stats.mold}\n{stats.percentage('mold'):.1f}%")
        self.small_var.set(f"{stats.small}\n{stats.percentage('small'):.1f}%")
        self.unknown_var.set(str(stats.unknown))
        calibration = WeightCalibration.load(self.config_data.calibration_path)
        if calibration.enabled:
            target = self.current_work_order.target_weight_g if self.current_work_order else 0.0
            self.weight_var.set(f"{stats.total_weight_g:.2f} g\n/ {target:.2f} g")
        else:
            self.weight_var.set("待校正\n--")
        self.false_reject_var.set(
            f"{stats.predicted_false_rejects}\n{stats.false_reject_rate:.1f}%"
        )

    def _set_state(self, state: MachineState) -> None:
        self.machine_state = state
        labels = {
            MachineState.STOPPED: ("停止", RED),
            MachineState.RUNNING: ("運轉中", GREEN),
            MachineState.PAUSED: ("暫停", YELLOW),
            MachineState.FAULT: ("異常", "#dc2626"),
        }
        text, color = labels[state]
        self.state_var.set(text)
        self.state_badge.configure(bg=color)

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.worker.stop()
        self.destroy()


class ProductionSettingsDialog(tk.Toplevel):
    def __init__(self, parent, database, current_work_order, on_saved) -> None:
        super().__init__(parent)
        self.database = database
        self.on_saved = on_saved
        self.title("生產設定")
        self.geometry("760x700")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        defaults = current_work_order
        self.variables = {
            "vendor": tk.StringVar(value=defaults.vendor_code if defaults else "001"),
            "variety": tk.StringVar(value=defaults.variety_code if defaults else "001"),
            "lot": tk.StringVar(value=defaults.material_lot if defaults else ""),
            "manufacture_date": tk.StringVar(
                value=defaults.material_manufacture_date if defaults else date.today().isoformat()
            ),
            "target_kg": tk.StringVar(
                value=f"{defaults.target_weight_g / 1000:g}" if defaults else ""
            ),
            "camera_index": tk.StringVar(value="0"),
        }
        form = ttk.Frame(self, padding=22)
        form.pack(fill="both", expand=True)
        fields = [
            ("廠商編號（3 位）", "vendor"),
            ("花生種類編號（3 位）", "variety"),
            ("物料批號", "lot"),
            ("物料製造日期 YYYY-MM-DD", "manufacture_date"),
            ("生產目標重量（kg）", "target_kg"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=8)
            ttk.Entry(form, textvariable=self.variables[key], width=34).grid(
                row=row, column=1, sticky="ew", pady=8
            )

        scan_frame = ttk.LabelFrame(form, text="GoPro 掃碼", padding=12)
        scan_frame.grid(row=len(fields), column=0, columnspan=2, sticky="ew", pady=(12, 8))
        ttk.Label(scan_frame, text="攝影機索引").pack(side="left")
        ttk.Entry(scan_frame, textvariable=self.variables["camera_index"], width=6).pack(
            side="left", padx=8
        )
        ttk.Button(scan_frame, text="開始掃碼", command=self._scan).pack(side="left")
        ttk.Label(
            form,
            text="掃碼結果會填入物料批號；目前同時嘗試 QR Code 與 OpenCV 一般條碼。",
            foreground="#666666",
            wraplength=520,
        ).grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", pady=(0, 16))

        ai_frame = ttk.LabelFrame(form, text="AI 分析數據", padding=10)
        ai_frame.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="nsew", pady=(0, 14))
        ai_text = tk.Text(
            ai_frame,
            height=8,
            wrap="word",
            font=("Microsoft JhengHei UI", 9),
        )
        ai_text.pack(fill="both", expand=True)
        ai_text.insert("1.0", AnalyticsService(self.database).deterministic_report())
        ai_text.configure(state="disabled")

        actions = ttk.Frame(form)
        actions.grid(row=len(fields) + 3, column=0, columnspan=2, sticky="e")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(actions, text="建立新工單", command=self._save).pack(side="left")
        form.grid_columnconfigure(1, weight=1)

    def _scan(self) -> None:
        try:
            camera_index = int(self.variables["camera_index"].get())
        except ValueError:
            messagebox.showerror("攝影機索引錯誤", "攝影機索引必須是整數。", parent=self)
            return
        BarcodeScanDialog(
            self,
            camera_index=camera_index,
            on_detected=lambda value: self.variables["lot"].set(value),
        )

    def _save(self) -> None:
        vendor = self.variables["vendor"].get().strip()
        variety = self.variables["variety"].get().strip()
        lot = self.variables["lot"].get().strip()
        manufacture_date = self.variables["manufacture_date"].get().strip()
        try:
            date.fromisoformat(manufacture_date)
            target_kg = float(self.variables["target_kg"].get())
        except ValueError:
            messagebox.showerror("格式錯誤", "請檢查製造日期與目標重量。", parent=self)
            return
        if not lot or target_kg <= 0:
            messagebox.showerror("資料不完整", "物料批號及正數目標重量為必填。", parent=self)
            return
        if not (vendor.isdigit() and len(vendor) == 3):
            messagebox.showerror("廠商編號錯誤", "廠商編號必須是 3 位數字。", parent=self)
            return
        if not (variety.isdigit() and len(variety) == 3):
            messagebox.showerror("種類編號錯誤", "花生種類編號必須是 3 位數字。", parent=self)
            return

        work_order = self.database.create_work_order(
            WorkOrderInput(
                vendor_code=vendor,
                variety_code=variety,
                material_lot=lot,
                material_manufacture_date=manufacture_date,
                target_weight_g=target_kg * 1000.0,
            )
        )
        self.on_saved(work_order)
        messagebox.showinfo("工單已建立", f"工單號：{work_order.work_order_no}", parent=self)
        self.destroy()


class BarcodeScanDialog(tk.Toplevel):
    def __init__(self, parent, camera_index: int, on_detected) -> None:
        super().__init__(parent)
        self.on_detected = on_detected
        self.decoder = BarcodeDecoder()
        self.photo = None
        self.title("GoPro 掃描物料批號")
        self.geometry("720x500")
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.preview = ttk.Label(self, text="正在開啟攝影機……", anchor="center")
        self.preview.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(self, text="將 QR Code 或條碼置於畫面中央").pack(pady=(0, 10))
        self.capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not self.capture.isOpened():
            self.capture.release()
            messagebox.showerror("無法開啟 GoPro", f"無法開啟攝影機索引 {camera_index}", parent=self)
            self.destroy()
            return
        self.after(10, self._tick)

    def _tick(self) -> None:
        ok, frame = self.capture.read()
        if not ok:
            self.after(100, self._tick)
            return
        decoded = self.decoder.decode(frame)
        if decoded is not None:
            value, code_type = decoded
            self.on_detected(value)
            messagebox.showinfo("掃碼完成", f"類型：{code_type}\n內容：{value}", parent=self)
            self._close()
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((680, 410), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self.photo, text="")
        self.after(30, self._tick)

    def _close(self) -> None:
        if getattr(self, "capture", None) is not None:
            self.capture.release()
        self.destroy()


class AnomalyDialog(tk.Toplevel):
    def __init__(self, parent, database, work_order_id, on_changed) -> None:
        super().__init__(parent)
        self.database = database
        self.work_order_id = work_order_id
        self.on_changed = on_changed
        self.title("異常狀況")
        self.geometry("1050x520")
        self.transient(parent)
        columns = ("id", "time", "severity", "code", "message", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": "ID",
            "time": "發生時間",
            "severity": "等級",
            "code": "代碼",
            "message": "內容",
            "status": "狀態",
        }
        widths = {"id": 55, "time": 145, "severity": 75, "code": 190, "message": 470, "status": 75}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=12)
        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="重新整理", command=self._refresh).pack(side="left")
        ttk.Button(actions, text="清除選取異常", command=self._clear_selected).pack(side="left", padx=8)
        ttk.Button(actions, text="關閉", command=self.destroy).pack(side="right")
        self._refresh()

    def _refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for anomaly in self.database.list_anomalies():
            status = "未清除" if anomaly.cleared_at is None else "已清除"
            self.tree.insert(
                "",
                "end",
                iid=str(anomaly.id),
                values=(
                    anomaly.id,
                    anomaly.created_at,
                    anomaly.severity,
                    anomaly.code,
                    anomaly.message,
                    status,
                ),
            )

    def _clear_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("尚未選取", "請先選擇一筆異常。", parent=self)
            return
        anomaly_id = int(selection[0])
        self.database.clear_anomaly(anomaly_id)
        self._refresh()
        self.on_changed()


class AIUpdateDialog(tk.Toplevel):
    def __init__(self, parent, config, database, detection_running: bool) -> None:
        super().__init__(parent)
        self.config_data = config
        self.database = database
        self.detection_running = detection_running
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.title("AI 更新與數據分析")
        self.geometry("980x700")
        self.transient(parent)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        analysis_tab = ttk.Frame(notebook, padding=14)
        training_tab = ttk.Frame(notebook, padding=14)
        notebook.add(analysis_tab, text="AI 數據分析")
        notebook.add(training_tab, text="模型更新")

        settings = ttk.Frame(analysis_tab)
        settings.pack(fill="x")
        self.qwen_model_var = tk.StringVar(value=config.qwen_model)
        ttk.Label(settings, text="連線").grid(row=0, column=0, sticky="w")
        ttk.Label(
            settings,
            text="本機 Ollama（127.0.0.1，禁止區網連線）",
            foreground="#166534",
        ).grid(row=0, column=1, padx=8, sticky="w")
        ttk.Label(settings, text="模型").grid(row=0, column=2, sticky="w", padx=(20, 0))
        ttk.Entry(settings, textvariable=self.qwen_model_var, width=18).grid(
            row=0, column=3, padx=8
        )
        buttons = ttk.Frame(analysis_tab)
        buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="計算統計", command=self._show_statistics).pack(side="left")
        ttk.Button(buttons, text="Qwen 分析", command=self._run_qwen).pack(side="left", padx=8)
        self.analysis_text = tk.Text(analysis_tab, wrap="word", font=("Microsoft JhengHei UI", 10))
        self.analysis_text.pack(fill="both", expand=True)

        sample_count = len(database.training_sample_rows())
        ttk.Label(
            training_tab,
            text=(
                f"目前完整原始訓練幀：{sample_count} 張\n"
                f"x 模型：{config.x_model_path}\n"
                f"初始 s 模型：{config.model_path}"
            ),
            justify="left",
        ).pack(anchor="w")
        warning = (
            "只使用無框線文字的完整原始幀。新模型訓練完成後會自動啟用；舊權重、"
            "評估資料與啟用歷史會保留，可隨時回復。資料不足兩個工單／批次時不允許訓練。"
        )
        ttk.Label(training_tab, text=warning, foreground="#a16207", wraplength=900).pack(
            anchor="w", pady=10
        )
        train_settings = ttk.Frame(training_tab)
        train_settings.pack(fill="x", pady=8)
        self.auto_conf_var = tk.StringVar(value="0.90")
        self.epochs_var = tk.StringVar(value="100")
        ttk.Label(train_settings, text="自動標註最低信心").pack(side="left")
        ttk.Entry(train_settings, textvariable=self.auto_conf_var, width=8).pack(side="left", padx=8)
        ttk.Label(train_settings, text="epochs").pack(side="left")
        ttk.Entry(train_settings, textvariable=self.epochs_var, width=8).pack(side="left", padx=8)
        self.train_button = ttk.Button(
            train_settings, text="開始離線更新", command=self._start_training
        )
        self.train_button.pack(side="left", padx=10)
        ttk.Button(
            train_settings,
            text="人工確認區",
            command=self._open_review_queue,
        ).pack(side="left", padx=4)
        if detection_running:
            self.train_button.configure(state="disabled")
            ttk.Label(
                training_tab,
                text="辨識運行中，為避免 GPU 資源衝突，模型更新已停用。",
                foreground="#b91c1c",
            ).pack(anchor="w")
        self.training_text = tk.Text(training_tab, wrap="word", height=20, font=("Consolas", 10))
        self.training_text.pack(fill="both", expand=True, pady=(10, 8))

        version_frame = ttk.LabelFrame(training_tab, text="模型版本與回復", padding=8)
        version_frame.pack(fill="both", expand=True)
        self.version_tree = ttk.Treeview(
            version_frame,
            columns=("active", "version", "created", "path"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        for column, title, width in (
            ("active", "使用中", 65),
            ("version", "版本", 230),
            ("created", "建立時間", 150),
            ("path", "權重路徑", 470),
        ):
            self.version_tree.heading(column, text=title)
            self.version_tree.column(column, width=width, anchor="w")
        self.version_tree.pack(fill="both", expand=True)
        ttk.Button(
            version_frame,
            text="使用／回復到選取版本",
            command=self._activate_selected_model,
        ).pack(anchor="e", pady=(6, 0))
        self._refresh_model_versions()
        self.after(100, self._poll_messages)

    def _show_statistics(self) -> None:
        report = AnalyticsService(self.database).deterministic_report()
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("1.0", report)

    def _run_qwen(self) -> None:
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("1.0", "正在請本地 Qwen 分析……")
        endpoint = self.config_data.qwen_endpoint
        model = self.qwen_model_var.get().strip()

        def work() -> None:
            try:
                report = AnalyticsService(self.database).qwen_report(
                    endpoint=endpoint,
                    model=model,
                    timeout_seconds=self.config_data.qwen_timeout_seconds,
                    num_predict=self.config_data.qwen_num_predict,
                )
                self.messages.put(("analysis", report))
            except Exception as exc:
                self.messages.put(("analysis_error", str(exc)))

        threading.Thread(target=work, name="qwen-analysis", daemon=True).start()

    def _start_training(self) -> None:
        try:
            confidence = float(self.auto_conf_var.get())
            epochs = int(self.epochs_var.get())
        except ValueError:
            messagebox.showerror("設定錯誤", "信心值與 epochs 格式錯誤。", parent=self)
            return
        if not (0.0 < confidence <= 1.0) or epochs <= 0:
            messagebox.showerror("設定錯誤", "信心值須介於 0～1，epochs 必須大於 0。", parent=self)
            return
        if not messagebox.askyesno(
            "開始離線模型更新",
            "此操作可能長時間占用 GPU。要開始 x 自動標註並訓練 s 候選模型嗎？",
            parent=self,
        ):
            return
        self.train_button.configure(state="disabled")
        self.training_text.delete("1.0", "end")

        def progress(message: str) -> None:
            self.messages.put(("training_progress", message))

        def work() -> None:
            try:
                output = TrainingPipeline(self.config_data, self.database).run(
                    auto_label_confidence=confidence,
                    epochs=epochs,
                    progress=progress,
                )
                self.messages.put(("training_done", str(output)))
            except Exception as exc:
                self.messages.put(("training_error", str(exc)))

        threading.Thread(target=work, name="offline-training", daemon=True).start()

    def _open_review_queue(self) -> None:
        TrainingReviewDialog(self, self.database)

    def _refresh_model_versions(self) -> None:
        for item in self.version_tree.get_children():
            self.version_tree.delete(item)
        for row in self.database.model_version_rows():
            self.version_tree.insert(
                "",
                "end",
                iid=str(row["version"]),
                values=(
                    "是" if row["is_active"] else "否",
                    row["version"],
                    row["created_at"],
                    row["weight_path"],
                ),
            )

    def _activate_selected_model(self) -> None:
        selection = self.version_tree.selection()
        if not selection:
            messagebox.showinfo("尚未選取", "請先選擇模型版本。", parent=self)
            return
        version = selection[0]
        if not messagebox.askyesno(
            "切換模型",
            f"下一次辨識要使用模型 {version} 嗎？",
            parent=self,
        ):
            return
        try:
            self.database.activate_model(version, reason="MANUAL_ROLLBACK_OR_SELECTION")
        except (ValueError, FileNotFoundError) as exc:
            messagebox.showerror("無法切換模型", str(exc), parent=self)
            return
        self._refresh_model_versions()
        self.training_text.insert("end", f"已切換到 {version}；下一次辨識生效。\n")

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, message = self.messages.get_nowait()
                if kind == "analysis":
                    self.analysis_text.delete("1.0", "end")
                    self.analysis_text.insert("1.0", message)
                elif kind == "analysis_error":
                    self.analysis_text.delete("1.0", "end")
                    self.analysis_text.insert("1.0", f"Qwen 分析失敗：{message}")
                else:
                    self.training_text.insert("end", message + "\n")
                    self.training_text.see("end")
                    if kind in {"training_done", "training_error"}:
                        self.train_button.configure(state="normal")
                    if kind == "training_done":
                        self._refresh_model_versions()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_messages)


class TrainingReviewDialog(tk.Toplevel):
    """顯示 x/s 不一致與低信心資料；保留圖片供後續人工標註。"""

    def __init__(self, parent, database: ProductionDatabase) -> None:
        super().__init__(parent)
        self.database = database
        self.rows_by_id = {}
        self.preview_photo = None
        self.title("訓練資料人工確認區")
        self.geometry("1250x720")
        self.transient(parent)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=10)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(right, weight=3)

        columns = ("id", "status", "work_order", "frame", "reason")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for column, title, width in (
            ("id", "ID", 55),
            ("status", "狀態", 145),
            ("work_order", "工單", 180),
            ("frame", "幀", 75),
            ("reason", "原因", 360),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._show_selected)

        self.preview = ttk.Label(
            right,
            text="選擇左側資料以查看：藍色為線上 s 座標，綠色為 x 候選標註",
            anchor="center",
        )
        self.preview.pack(fill="both", expand=True)
        self.path_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.path_var, wraplength=690).pack(fill="x", pady=6)

        actions = ttk.Frame(self, padding=(10, 0, 10, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="接受 X 標註", command=self._approve_x).pack(side="left")
        ttk.Button(actions, text="保留供人工標註", command=self._mark_manual).pack(
            side="left", padx=8
        )
        ttk.Button(actions, text="排除本次訓練", command=self._reject).pack(side="left")
        ttk.Button(actions, text="關閉", command=self.destroy).pack(side="right")
        self._refresh()

    def _refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = self.database.training_sample_rows(
            statuses=("NEEDS_REVIEW", "NEEDS_MANUAL_LABEL")
        )
        self.rows_by_id = {int(row["id"]): row for row in rows}
        for row in rows:
            self.tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    row["review_status"],
                    row["work_order_no"],
                    row["frame_number"],
                    row["review_reason"],
                ),
            )

    def _selected_row(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return self.rows_by_id.get(int(selection[0]))

    def _show_selected(self, _event=None) -> None:
        row = self._selected_row()
        if row is None:
            return
        image_path = Path(row["image_path"])
        metadata_path = Path(row["metadata_path"])
        frame = cv2.imread(str(image_path))
        if frame is None:
            self.preview.configure(text="無法讀取原始幀", image="")
            return
        height, width = frame.shape[:2]
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {"objects": []}
        for item in metadata.get("objects", []):
            x1, y1, x2, y2 = [int(value) for value in item.get("bbox_xyxy", [0, 0, 0, 0])]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 100, 0), 2)
            cv2.putText(
                frame,
                f"S {item.get('class_name', '?')} {float(item.get('confidence', 0)):.2f}",
                (x1, max(18, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 100, 0),
                2,
            )

        x_labels_path = Path(row["x_labels_path"]) if row["x_labels_path"] else None
        class_names = {0: "normal", 1: "mold", 2: "small"}
        if x_labels_path and x_labels_path.exists():
            for line in x_labels_path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) != 5:
                    continue
                class_id = int(parts[0])
                x_center, y_center, box_width, box_height = map(float, parts[1:])
                x1 = int((x_center - box_width / 2) * width)
                x2 = int((x_center + box_width / 2) * width)
                y1 = int((y_center - box_height / 2) * height)
                y2 = int((y_center + box_height / 2) * height)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 0), 2)
                cv2.putText(
                    frame,
                    f"X {class_names.get(class_id, class_id)}",
                    (x1, min(height - 8, y2 + 18)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 220, 0),
                    2,
                )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((700, 590), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self.preview_photo, text="")
        self.path_var.set(str(image_path))

    def _approve_x(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        if not row["x_labels_path"] or not Path(row["x_labels_path"]).exists():
            messagebox.showwarning("沒有 X 標註", "此資料尚無可接受的 x 候選標註。", parent=self)
            return
        self.database.update_training_sample_review(
            row["id"], "APPROVED", "人工確認並接受 x 候選標註"
        )
        self._refresh()

    def _mark_manual(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self.database.update_training_sample_review(
            row["id"], "NEEDS_MANUAL_LABEL", "保留完整原始幀與座標供人工標註"
        )
        self._refresh()

    def _reject(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        self.database.update_training_sample_review(
            row["id"], "REJECTED", "人工排除，不加入本次訓練"
        )
        self._refresh()


def run_app() -> None:
    app = PeanutProductionApp()
    app.mainloop()
