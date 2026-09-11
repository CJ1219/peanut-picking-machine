from __future__ import annotations

import queue
import json
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from .analytics import AnalyticsService
from .barcode import BarcodeDecoder
from .config import AppConfig
from .database import ProductionDatabase
from .detection import DetectionWorker
from .gopro_detection import GoProDetectionWorker
from detect_open_gopro import (
    DEFAULT_ARDUINO_PORT,
    DEFAULT_GOPRO_SERIAL,
    GOPRO_WEBCAM_FOV,
    GOPRO_WEBCAM_RESOLUTION,
)
from .domain import MachineState, PeanutRecord, ProductionStats, Severity, WorkerEvent, WorkOrderInput
from .training import TrainingPipeline
from .model_registry import file_hash
from .test_work_orders import get_test_work_order, parse_test_work_order_number


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
        self.source_mode_var = tk.StringVar(value="GoPro 生產（控制 Arduino）")
        self.arduino_port_var = tk.StringVar(value=DEFAULT_ARDUINO_PORT)
        self.gopro_serial_var = tk.StringVar(value=DEFAULT_GOPRO_SERIAL)
        self.last_peanut_var = tk.StringVar(value="尚無辨識資料")
        self.normal_var = tk.StringVar(value="0\n0.0%")
        self.mold_var = tk.StringVar(value="0\n0.0%")
        self.small_var = tk.StringVar(value="0\n0.0%")
        self.unknown_var = tk.StringVar(value="0")
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

        source_bar = tk.Frame(self, bg=PANEL, padx=16, pady=6)
        source_bar.pack(fill="x", padx=20, pady=(0, 8))
        ttk.Combobox(source_bar, textvariable=self.source_mode_var,
                     values=("影片測試", "GoPro 生產（控制 Arduino）"),
                     state="readonly", width=28).pack(side="left")
        for title, variable in (("Arduino COM：", self.arduino_port_var),
                                ("GoPro 序號尾碼：", self.gopro_serial_var)):
            tk.Label(source_bar, text=title, bg=PANEL, fg=TEXT).pack(side="left", padx=(14, 4))
            ttk.Entry(source_bar, textvariable=variable, width=10).pack(side="left")
        tk.Label(source_bar, text="生產模式會初始化及控制撥桿", bg=PANEL, fg=YELLOW).pack(side="left", padx=12)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=20)
        body.grid_columnconfigure(0, weight=4)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        # 固定影像容器，避免 Tk Label 依目前影像尺寸反覆改變 requested size，
        # 造成畫面逐步放大並把底部控制列推出視窗。
        video_panel = tk.Frame(
            body, bg="black", width=self.config_data.display_width,
            height=self.config_data.display_height,
            highlightbackground="#374151", highlightthickness=1,
        )
        video_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        video_panel.grid_propagate(False)
        self.video_canvas = tk.Canvas(
            video_panel,
            bg="black",
            highlightthickness=0,
        )
        self.video_canvas.pack(fill="both", expand=True)
        self.video_canvas.create_text(
            0, 0,
            text="辨識畫面",
            fill=MUTED,
            font=("Microsoft JhengHei UI", 16),
            tags="placeholder",
        )
        self.video_canvas.bind("<Configure>", self._center_video_placeholder)
        self.video_canvas_image_id = None

        side = tk.Frame(body, bg=BG)
        side.grid(row=0, column=1, sticky="nsew")
        stats_grid = tk.Frame(side, bg=BG)
        stats_grid.pack(fill="x")
        for column in range(2):
            stats_grid.grid_columnconfigure(column, weight=1)
        self._stat_card(stats_grid, 0, 0, "NORMAL", self.normal_var, GREEN)
        self._stat_card(stats_grid, 0, 1, "MOLD", self.mold_var, RED)
        self._stat_card(stats_grid, 1, 0, "SMALL", self.small_var, YELLOW)
        self._stat_card(stats_grid, 1, 1, "預估誤排除", self.false_reject_var, "#c084fc")

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
        ttk.Button(controls, text="開始生產", command=self._start_detection).pack(side="left")
        self.pause_button = ttk.Button(controls, text="暫停", command=self._toggle_pause)
        self.pause_button.pack(side="left", padx=8)
        ttk.Button(controls, text="停止生產", command=self._stop_detection).pack(side="left")
        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=14)
        ttk.Button(controls, text="生產設定", command=self._open_production_settings).pack(side="left")
        ttk.Button(controls, text="生產批次紀錄", command=self._open_batch_history).pack(
            side="left", padx=(8, 0)
        )
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
        if (
            self.worker is not None
            and self.worker.is_alive()
            and not getattr(self.worker, "monitoring_fault", False)
        ):
            messagebox.showwarning("辨識進行中", "請先停止辨識再建立新工單。", parent=self)
            return
        ProductionSettingsDialog(
            self,
            self.database,
            self.current_work_order,
            gopro_serial=self.gopro_serial_var.get().strip(),
            on_saved=self._on_work_order_saved,
        )

    def _on_work_order_saved(self, work_order) -> None:
        self.current_work_order = work_order
        self._set_state(MachineState.STOPPED)
        self._refresh_work_order()
        self._refresh_stats()
        self.status_var.set(f"工單 {work_order.work_order_no} 已建立，可以開始生產辨識")

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
            if getattr(self.worker, "monitoring_fault", False):
                self.status_var.set("請先按黃色按鈕完成異常重新檢查")
                return
            if self.machine_state in {MachineState.PAUSED, MachineState.STOPPED}:
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

        source_path = Path(self.video_path_var.get().strip())
        live = self.source_mode_var.get().startswith("GoPro")
        if not live and not source_path.is_file():
            messagebox.showerror("影片不存在", f"找不到影片：\n{source_path}", parent=self)
            return

        worker_class = GoProDetectionWorker if live else DetectionWorker
        options = {}
        if live:
            port = self.arduino_port_var.get().strip()
            serial = self.gopro_serial_var.get().strip()
            if not port or not serial:
                messagebox.showerror("缺少連線設定", "請填入 Arduino COM 與 GoPro 序號尾碼。", parent=self)
                return
            options = {"arduino_port": port, "gopro_serial": serial}
        self.worker = worker_class(
            config=self.config_data,
            database=self.database,
            work_order=self.current_work_order,
            video_source=source_path,
            event_queue=self.worker_events,
            **options,
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
                f"生產中｜Arduino 輸送已啟動｜來源 {values['width']}×{values['height']}｜"
                f"{values['fps']:.2f} FPS"
            )
        elif event.kind == "peanut":
            self._show_last_peanut(event.payload)
        elif event.kind == "stats":
            self._apply_stats(event.payload)
        elif event.kind == "false_reject":
            self.status_var.set(f"第 {event.payload.sequence_no} 顆 normal 被標記為預估誤排")
            self._refresh_stats()
        elif event.kind == "video_finished":
            self.status_var.set("影片播放與辨識完成")
        elif event.kind == "stopped":
            if self.machine_state != MachineState.FAULT:
                self._set_state(MachineState.STOPPED)
            self.pause_button.configure(text="暫停")
        elif event.kind == "arduino_state":
            state = str(event.payload)
            if state == "RUNNING":
                self._set_state(MachineState.RUNNING)
                self.pause_button.configure(text="暫停")
                direction = getattr(self.worker, "arduino_direction", "L")
                self.status_var.set(f"Arduino 已啟動輸送｜方向 {direction}")
                if self.current_work_order:
                    self.database.set_work_order_status(self.current_work_order.id, "RUNNING")
            elif state == "STOPPED":
                self._set_state(MachineState.STOPPED)
                self.pause_button.configure(text="繼續")
                self.status_var.set("Arduino 實體紅色按鈕已停止輸送")
                if self.current_work_order:
                    self.database.set_work_order_status(self.current_work_order.id, "STOPPED")
            elif state == "FAULT":
                self._set_state(MachineState.FAULT)
                self.status_var.set("Arduino 已進入異常燈號狀態")
        elif event.kind == "arduino_yellow":
            self._handle_arduino_yellow()
        elif event.kind == "arduino_direction":
            self.status_var.set(f"Arduino 選擇開關方向：{event.payload}")
        elif event.kind == "error":
            self._set_state(MachineState.FAULT)
            message = str(event.payload.get("message", "未知錯誤"))
            code = str(event.payload.get("code", ""))
            self.status_var.set(
                f"GoPro 重啟失敗：{message}（請確認相機後再按黃色按鈕重試）"
                if code == "CAMERA_CONNECTION_ERROR"
                else message
            )
            # 相機重試失敗會留在主畫面提示，避免跳出必須按確定的視窗。
            if code != "CAMERA_CONNECTION_ERROR":
                messagebox.showerror("Python 辨識錯誤", message, parent=self)

    def _handle_arduino_yellow(self) -> None:
        active = self.database.list_anomalies(active_only=True)
        retry_camera = any(item.code == "CAMERA_CONNECTION_ERROR" for item in active)
        persistent = [item for item in active if self._anomaly_still_present(item)]
        persistent_ids = {item.id for item in persistent}
        cleared = 0
        for item in active:
            if item.id not in persistent_ids:
                self.database.clear_anomaly(item.id)
                cleared += 1

        if persistent:
            self._set_state(MachineState.FAULT)
            if isinstance(self.worker, GoProDetectionWorker):
                self.worker.set_indicator_state("FAULT")
            names = "、".join(item.code for item in persistent)
            self.status_var.set(f"黃色按鈕：已清除 {cleared} 筆；仍有異常：{names}")
            return

        if retry_camera and isinstance(self.worker, GoProDetectionWorker):
            # 相機連線異常可由黃色按鈕清除後重新建立 GoPro worker。
            old_worker = self.worker
            old_worker.stop()
            self.worker = None
            self._set_state(MachineState.STOPPED)
            self.status_var.set("已清除相機異常，正在重新嘗試連線 GoPro……")
            self.after(300, self._start_detection)
            return

        running = bool(
            self.worker
            and self.worker.is_alive()
            and not getattr(self.worker, "monitoring_fault", False)
            and not self.worker.pause_event.is_set()
        )
        next_state = MachineState.RUNNING if running else MachineState.STOPPED
        self._set_state(next_state)
        if isinstance(self.worker, GoProDetectionWorker):
            self.worker.set_indicator_state("RUNNING" if running else "STOPPED")
        self.status_var.set(f"黃色按鈕：已清除 {cleared} 筆已不存在的異常")

    def _open_batch_history(self) -> None:
        ProductionBatchHistoryDialog(
            self,
            self.database,
            data_root=self.config_data.data_root,
            deletion_allowed=not bool(self.worker and self.worker.is_alive()),
            on_changed=self._after_batch_history_changed,
        )

    def _after_batch_history_changed(self) -> None:
        self.current_work_order = self.database.latest_work_order()
        self._refresh_work_order()
        self._refresh_stats()
        if self.current_work_order is None:
            self.status_var.set("尚無生產工單，請先建立或掃描工單")
        else:
            self.status_var.set(f"目前工單：{self.current_work_order.work_order_no}")

    def _anomaly_still_present(self, anomaly) -> bool:
        if anomaly.code == "MISSING_PRODUCTION_DATA":
            return self.current_work_order is None
        # Runtime/camera/model errors are historical unless detected again.
        return False

    def _display_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        # 只使用固定容器的實際大小計算等比例縮放，避免影像尺寸形成幾何回饋。
        available_width = max(320, self.video_canvas.winfo_width() - 2)
        available_height = max(240, self.video_canvas.winfo_height() - 2)
        image.thumbnail((available_width, available_height), Image.Resampling.LANCZOS)
        self.video_photo = ImageTk.PhotoImage(image=image)
        self.video_canvas.delete("placeholder")
        if self.video_canvas_image_id is None:
            self.video_canvas_image_id = self.video_canvas.create_image(
                available_width // 2, available_height // 2,
                image=self.video_photo, anchor="center",
            )
        else:
            self.video_canvas.itemconfigure(
                self.video_canvas_image_id, image=self.video_photo
            )
        self.video_canvas.coords(
            self.video_canvas_image_id,
            self.video_canvas.winfo_width() // 2,
            self.video_canvas.winfo_height() // 2,
        )

    def _center_video_placeholder(self, _event=None) -> None:
        """Keep the idle text centered in the actual canvas, regardless of window size."""
        items = self.video_canvas.find_withtag("placeholder")
        if items:
            self.video_canvas.coords(
                items[0], self.video_canvas.winfo_width() // 2,
                self.video_canvas.winfo_height() // 2,
            )

    def _show_last_peanut(self, record: PeanutRecord) -> None:
        boundary = (
            f"{record.boundary_between[0]}-{record.boundary_between[1]}"
            if record.boundary_between
            else "否"
        )
        self.last_peanut_var.set(
            f"序號：P{record.sequence_no:06d}\n"
            f"紀錄狀態：{record.record_status}\n"
            f"類別：{record.classification.upper()}\n"
            f"中央信心：{record.confidence_center:.3f}\n"
            f"觀測平均信心：{record.confidence_mean:.3f}\n"
            f"有效觀測幀：{record.valid_frames}\n"
            f"平均面積：{record.area_mean_px2:.1f} px²\n"
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
            self.status_var.set("正在釋放 GoPro / Arduino，請稍候……")
            self.after(100, self._on_close)
            return
        self.destroy()


class ProductionSettingsDialog(tk.Toplevel):
    def __init__(self, parent, database, current_work_order, gopro_serial, on_saved) -> None:
        super().__init__(parent)
        self.database = database
        self.gopro_serial = gopro_serial
        self.on_saved = on_saved
        self.title("生產設定")
        self.geometry("760x760")
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
            "quick_number": tk.StringVar(value=""),
        }
        form = ttk.Frame(self, padding=22)
        form.pack(fill="both", expand=True)
        fields = [
            ("廠商編號（3 位）", "vendor"),
            ("花生種類編號（3 位）", "variety"),
            ("物料批號", "lot"),
            ("物料製造日期 YYYY-MM-DD", "manufacture_date"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=8)
            ttk.Entry(form, textvariable=self.variables[key], width=34).grid(
                row=row, column=1, sticky="ew", pady=8
            )

        quick_frame = ttk.LabelFrame(form, text="快速測試工單", padding=12)
        quick_frame.grid(row=len(fields), column=0, columnspan=2, sticky="ew", pady=(12, 8))
        ttk.Label(quick_frame, text="條碼編號 1–100").pack(side="left")
        quick_entry = ttk.Entry(quick_frame, textvariable=self.variables["quick_number"], width=8)
        quick_entry.pack(side="left", padx=8)
        quick_entry.bind("<Return>", lambda _event: self._load_quick_work_order())
        ttk.Button(quick_frame, text="載入工單", command=self._load_quick_work_order).pack(side="left")

        scan_frame = ttk.LabelFrame(form, text="GoPro 掃碼", padding=12)
        scan_frame.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(scan_frame, text="開始掃碼", command=self._scan).pack(side="left")
        ttk.Label(scan_frame, text="使用目前設定的 GoPro", foreground="#666666").pack(
            side="left", padx=12
        )
        ttk.Label(
            form,
            text="掃描測試 QR Code 後會自動帶入整筆工單資料。",
            foreground="#666666",
            wraplength=520,
        ).grid(row=len(fields) + 2, column=0, columnspan=2, sticky="w", pady=(0, 16))

        ai_frame = ttk.LabelFrame(form, text="AI 分析數據", padding=10)
        ai_frame.grid(row=len(fields) + 3, column=0, columnspan=2, sticky="nsew", pady=(0, 14))
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
        actions.grid(row=len(fields) + 4, column=0, columnspan=2, sticky="e")
        ttk.Button(actions, text="取消", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(actions, text="建立新工單", command=self._save).pack(side="left")
        form.grid_columnconfigure(1, weight=1)

    def _scan(self) -> None:
        BarcodeScanDialog(
            self,
            gopro_serial=self.gopro_serial,
            on_detected=self._load_barcode_value,
        )

    def _load_quick_work_order(self) -> None:
        self._load_barcode_value(self.variables["quick_number"].get())

    def _load_barcode_value(self, value: str) -> bool:
        number = parse_test_work_order_number(value)
        if number is None:
            messagebox.showerror(
                "無法載入工單", "條碼內容必須是測試工單編號 1–100。", parent=self
            )
            return False
        row = get_test_work_order(number)
        self.variables["quick_number"].set(str(number))
        self.variables["vendor"].set(row.vendor_code)
        self.variables["variety"].set(row.variety_code)
        self.variables["lot"].set(row.material_lot)
        self.variables["manufacture_date"].set(row.material_manufacture_date)
        return True

    def _save(self) -> None:
        vendor = self.variables["vendor"].get().strip()
        variety = self.variables["variety"].get().strip()
        lot = self.variables["lot"].get().strip()
        manufacture_date = self.variables["manufacture_date"].get().strip()
        try:
            date.fromisoformat(manufacture_date)
        except ValueError:
            messagebox.showerror("格式錯誤", "請檢查物料製造日期。", parent=self)
            return
        if not lot:
            messagebox.showerror("資料不完整", "物料批號為必填。", parent=self)
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
                # 舊版資料庫欄位仍要求值；重量功能已停用，此值不參與任何運算。
                target_weight_g=1.0,
            )
        )
        self.on_saved(work_order)
        messagebox.showinfo("工單已建立", f"工單號：{work_order.work_order_no}", parent=self)
        self.destroy()


class BarcodeScanDialog(tk.Toplevel):
    def __init__(self, parent, gopro_serial: str, on_detected) -> None:
        super().__init__(parent)
        self.on_detected = on_detected
        self.decoder = BarcodeDecoder()
        self.photo = None
        self.gopro_serial = gopro_serial
        self.capture = None
        self.gopro = None
        self.frame_queue = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.title("GoPro 掃描物料批號")
        self.geometry("720x500")
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.preview = ttk.Label(self, text="正在開啟攝影機……", anchor="center")
        self.preview.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(self, text="將 QR Code 或條碼置於畫面中央").pack(pady=(0, 10))
        threading.Thread(target=self._capture_loop, name="gopro-barcode-scanner", daemon=True).start()
        self.after(30, self._poll_frames)

    def _capture_loop(self) -> None:
        try:
            from multi_webcam.webcam import Webcam

            self.gopro = Webcam(self.gopro_serial)
            self.gopro.enable()
            self.gopro.start(
                port=8555,
                resolution=GOPRO_WEBCAM_RESOLUTION,
                fov=GOPRO_WEBCAM_FOV,
            )
            self.capture = cv2.VideoCapture(
                "udp://0.0.0.0:8555?overrun_nonfatal=1&fifo_size=50000000",
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000],
            )
            if not self.capture.isOpened():
                raise RuntimeError("OpenCV 無法開啟 GoPro 掃碼串流")
            while not self.stop_event.is_set():
                ok, frame = self.capture.read()
                if not ok:
                    continue
                decoded = self.decoder.decode(frame)
                item = ("detected", decoded) if decoded is not None else ("frame", frame)
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
                self.frame_queue.put_nowait(item)
                if decoded is not None:
                    return
        except Exception as exc:
            self.frame_queue.put(("error", str(exc)))
        finally:
            if self.capture is not None:
                self.capture.release()
            if self.gopro is not None:
                for action in (self.gopro.stop, self.gopro.disable):
                    try:
                        action()
                    except Exception:
                        pass

    def _poll_frames(self) -> None:
        try:
            kind, payload = self.frame_queue.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(30, self._poll_frames)
            return
        if kind == "error":
            messagebox.showerror("無法開啟 GoPro", payload, parent=self)
            self._close()
            return
        if kind == "detected":
            value, code_type = payload
            if self.on_detected(value):
                messagebox.showinfo("掃碼完成", f"類型：{code_type}\n內容：{value}", parent=self)
            self._close()
            return
        else:
            frame = payload
            self._show_frame(frame)
        if self.winfo_exists():
            self.after(30, self._poll_frames)

    def _show_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((680, 410), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self.photo, text="")

    def _close(self) -> None:
        self.stop_event.set()
        self.destroy()


class ProductionBatchHistoryDialog(tk.Toplevel):
    def __init__(self, parent, database, data_root: Path, deletion_allowed: bool, on_changed) -> None:
        super().__init__(parent)
        self.database = database
        self.data_root = Path(data_root).resolve()
        self.deletion_allowed = deletion_allowed
        self.on_changed = on_changed
        self.title("生產批次紀錄")
        self.geometry("1180x620")
        self.transient(parent)
        columns = ("id", "work_order", "date", "vendor", "variety", "lot", "count", "normal", "ng", "status")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
        definitions = (
            ("id", "ID", 55), ("work_order", "工單號", 175), ("date", "生產日", 95),
            ("vendor", "廠商", 60), ("variety", "品種", 60), ("lot", "物料批號", 150),
            ("count", "總數", 55), ("normal", "正常", 55),
            ("ng", "NG", 55), ("status", "狀態", 80),
        )
        for column, title, width in definitions:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(12, 8))
        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="重新整理", command=self._refresh).pack(side="left")
        self.delete_button = ttk.Button(actions, text="刪除選取批次", command=self._delete_selected)
        self.delete_button.pack(side="left", padx=8)
        if not deletion_allowed:
            self.delete_button.configure(state="disabled")
            ttk.Label(actions, text="生產辨識運行時不可刪除", foreground="#b45309").pack(side="left")
        ttk.Button(actions, text="關閉", command=self.destroy).pack(side="right")
        self._refresh()

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in self.database.list_production_batches():
            self.tree.insert("", "end", iid=str(row["id"]), values=(
                row["id"], row["work_order_no"], row["production_date"], row["vendor_code"],
                row["variety_code"], row["material_lot"], row["peanut_count"],
                row["normal_count"], row["ng_count"], row["status"],
            ))

    def _delete_selected(self) -> None:
        ids = [int(item) for item in self.tree.selection()]
        if not ids:
            messagebox.showwarning("未選取批次", "請先選取要刪除的一筆或多筆批次。", parent=self)
            return
        if not messagebox.askyesno(
            "確認刪除", f"確定刪除選取的 {len(ids)} 個生產批次及其辨識紀錄？", parent=self
        ):
            return
        paths = self.database.delete_production_batches(ids)
        for raw_path in paths:
            try:
                path = Path(raw_path).resolve()
                if path.is_relative_to(self.data_root) and path.is_file():
                    path.unlink()
            except (OSError, ValueError):
                pass
        for child in self.data_root.rglob("*"):
            if child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        self.on_changed()
        self._refresh()


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
        self.analysis_notebook = ttk.Notebook(analysis_tab)
        self.analysis_notebook.pack(fill="both", expand=True)
        brief_tab = ttk.Frame(self.analysis_notebook, padding=6)
        detail_tab = ttk.Frame(self.analysis_notebook, padding=6)
        self.analysis_notebook.add(brief_tab, text="簡述")
        self.analysis_notebook.add(detail_tab, text="詳細說明")
        self.analysis_brief_text = tk.Text(brief_tab, wrap="word", font=("Microsoft JhengHei UI", 11))
        self.analysis_brief_text.pack(fill="both", expand=True)
        self.analysis_detail_text = tk.Text(detail_tab, wrap="word", font=("Microsoft JhengHei UI", 10))
        self.analysis_detail_text.pack(fill="both", expand=True)
        self.analysis_text = self.analysis_detail_text

        sample_count = len(database.training_sample_rows())
        base_counts = {
            split: sum(
                1 for path in (config.base_dataset_path / "images" / split).glob("*")
                if path.is_file()
            )
            for split in ("train", "val", "test")
        }
        labeled_rows = database.training_sample_rows(
            statuses=("CAPTURED", "AUTO_CANDIDATE", "APPROVED", "NEEDS_REVIEW", "NEEDS_MANUAL_LABEL", "X_TRAINING")
        )
        x_label_count = sum(1 for row in labeled_rows if row["x_labels_path"])
        x_training_count = sum(1 for row in labeled_rows if row["review_status"] == "X_TRAINING")
        mixed_counts = {"train": 0, "val": 0, "test": 0}
        mixed_dirs = [
            path / "dataset" for path in config.training_root.glob("training_*")
            if (path / "dataset").is_dir()
        ]
        if mixed_dirs:
            latest_mixed = max(mixed_dirs, key=lambda path: path.stat().st_mtime)
            mixed_counts = {
                split: sum(1 for item in (latest_mixed / "images" / split).glob("*") if item.is_file())
                for split in ("train", "val", "test")
            }
        ttk.Label(
            training_tab,
            text=(
                f"目前完整原始訓練幀：{sample_count} 張\n"
                f"自動標註模型（M）：{config.x_model_path}\n"
                f"M 訓練起始模型：{config.m_model_path}\n\n"
                f"原始 dataset：train {base_counts['train']} + val {base_counts['val']} + "
                f"test {base_counts['test']} = {sum(base_counts.values())} 張\n"
                f"已保存 X 標註：{x_label_count} 筆；已加入 X／M 訓練集：{x_training_count} 筆\n"
                f"最新混合資料集：train {mixed_counts['train']} + val {mixed_counts['val']} + "
                f"test {mixed_counts['test']} = {sum(mixed_counts.values())} 張"
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
            train_settings, text="訓練M", command=self._start_training
        )
        self.train_button.pack(side="left", padx=10)
        self.m_train_button = ttk.Button(
            train_settings, text="訓練X", command=self._start_m_training
        )
        self.m_train_button.pack(side="left", padx=4)
        ttk.Button(
            train_settings,
            text="人工確認",
            command=self._open_review_queue,
        ).pack(side="left", padx=4)
        if detection_running:
            self.train_button.configure(state="disabled")
            self.m_train_button.configure(state="disabled")
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
        self._set_analysis_report(report, complete=True)

    def _set_analysis_report(self, report: str, complete: bool) -> None:
        summary, detail = AnalyticsService.report_sections(report)
        brief = ["分析狀態：已完成" if complete else "分析狀態：可能未完成", "", summary]
        self.analysis_brief_text.delete("1.0", "end")
        self.analysis_brief_text.insert("1.0", "\n".join(brief))
        self.analysis_detail_text.delete("1.0", "end")
        self.analysis_detail_text.insert("1.0", detail)
        self.analysis_notebook.select(0 if complete else 1)

    def _run_qwen(self) -> None:
        self._set_analysis_report("正在請本地 Qwen 分析……", complete=False)
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
                self.messages.put(("analysis", (report, report.rstrip().endswith("【分析完成】"))))
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
            "此操作可能長時間占用 GPU。要開始 x 自動標註並訓練 M 候選模型嗎？",
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

    def _start_m_training(self) -> None:
        try:
            epochs = int(self.epochs_var.get())
        except ValueError:
            messagebox.showerror("設定錯誤", "epochs 必須是整數。", parent=self)
            return
        if epochs <= 0:
            messagebox.showerror("設定錯誤", "epochs 必須大於 0。", parent=self)
            return
        if not messagebox.askyesno(
            "訓練 M 模型", "將使用已加入 X 訓練集的人工標註接續訓練 M 候選模型，繼續嗎？", parent=self
        ):
            return
        self.m_train_button.configure(state="disabled")
        self.training_text.insert("end", "開始訓練 M 模型……\n")

        def progress(message: str) -> None:
            self.messages.put(("m_training_progress", message))

        def work() -> None:
            try:
                output = TrainingPipeline(self.config_data, self.database).train_m_model(
                    epochs=epochs, progress=progress
                )
                self.messages.put(("m_training_done", str(output)))
            except Exception as exc:
                self.messages.put(("m_training_error", str(exc)))

        threading.Thread(target=work, name="m-model-training", daemon=True).start()

    def _open_review_queue(self) -> None:
        TrainingReviewDialog(
            self,
            self.database,
            data_root=self.config_data.data_root,
            config=self.config_data,
        )

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
                    report, complete = message
                    self._set_analysis_report(report, complete=complete)
                elif kind == "analysis_error":
                    self._set_analysis_report(f"Qwen 分析失敗：{message}", complete=False)
                else:
                    self.training_text.insert("end", message + "\n")
                    self.training_text.see("end")
                    if kind in {"training_done", "training_error"}:
                        self.train_button.configure(state="normal")
                    if kind in {"m_training_done", "m_training_error"}:
                        self.m_train_button.configure(state="normal")
                    if kind == "training_done":
                        self._refresh_model_versions()
                    if kind == "m_training_done":
                        self._refresh_model_versions()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_messages)


class TrainingReviewDialog(tk.Toplevel):
    """顯示 X/M 不一致與低信心資料；保留圖片供後續人工標註。"""

    def __init__(
        self,
        parent,
        database: ProductionDatabase,
        data_root: Path | None = None,
        config: AppConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.database_config = config or AppConfig()
        self.data_root = Path(data_root or Path.cwd()).resolve()
        self._resolved_paths: dict[str, Path | None] = {}
        self.refresh_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.refreshing = False
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
            text="選擇左側資料以查看：藍色為線上 M 座標，綠色為 X 候選標註",
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
        ttk.Button(actions, text="加入X訓練集", command=self._add_selected_x_training).pack(
            side="left", padx=(12, 4)
        )
        ttk.Button(actions, text="編輯標註", command=self._open_annotation_editor).pack(
            side="left", padx=(12, 4)
        )
        self.single_refresh_button = ttk.Button(
            actions, text="X標註刷新（單張）", command=self._refresh_selected_x
        )
        self.single_refresh_button.pack(side="left", padx=(14, 4))
        self.batch_refresh_button = ttk.Button(
            actions, text="X標註刷新（批量）", command=self._refresh_all_x
        )
        self.batch_refresh_button.pack(side="left")
        ttk.Button(actions, text="關閉", command=self.destroy).pack(side="right")
        self._refresh()

    def _refresh(self) -> None:
        self._refresh_select(None)

    def _refresh_select(self, preferred_index: int | None) -> None:
        old_selection = self.tree.selection()
        old_items = list(self.tree.get_children())
        old_index = old_items.index(old_selection[0]) if old_selection and old_selection[0] in old_items else None
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
        items = list(self.tree.get_children())
        if items:
            index = preferred_index if preferred_index is not None else old_index
            if index is not None:
                index = min(index, len(items) - 1)
                self.tree.selection_set(items[index])
                self.tree.focus(items[index])
                self.tree.see(items[index])

    def _selected_row(self):
        selection = self.tree.selection()
        if not selection:
            return None
        return self.rows_by_id.get(int(selection[0]))

    def _next_index_after_selected(self) -> int:
        items = list(self.tree.get_children())
        selection = self.tree.selection()
        if not selection or selection[0] not in items:
            return 0
        return items.index(selection[0])

    def _refresh_selected_x(self) -> None:
        row = self._selected_row()
        if row is None:
            messagebox.showinfo("尚未選取", "請先選擇一筆資料。", parent=self)
            return
        self._start_x_refresh([int(row["id"])])

    def _open_annotation_editor(self) -> None:
        row = self._selected_row()
        if row is None:
            messagebox.showinfo("尚未選取", "請先選擇一筆資料。", parent=self)
            return
        AnnotationEditorDialog(
            self,
            row,
            self.data_root,
            self.database,
            self.database_config,
            on_saved=self._refresh,
        )

    def _add_selected_x_training(self) -> None:
        row = self._selected_row()
        if row is None:
            messagebox.showinfo("尚未選取", "請先選擇一筆資料。", parent=self)
            return
        if self._resolve_path(row["x_labels_path"]) is None:
            messagebox.showwarning("沒有 X 標註", "請先按「編輯標註」建立 X 框。", parent=self)
            return
        next_index = self._next_index_after_selected()
        self.database.set_training_sample_review_status(int(row["id"]), "X_TRAINING")
        self.database.set_training_sample_x_labels(
            int(row["id"]), self._resolve_path(row["x_labels_path"]),
            "加入 X 與 S 模型訓練集"
        )
        self._refresh_select(next_index)

    def _refresh_all_x(self) -> None:
        ids = [int(row["id"]) for row in self.rows_by_id.values()]
        if not ids:
            messagebox.showinfo("沒有資料", "目前沒有可刷新 X 標註的資料。", parent=self)
            return
        if not messagebox.askyesno(
            "批量刷新 X 標註",
            f"將重新分析目前 {len(ids)} 筆資料，可能需要一些時間。繼續嗎？",
            parent=self,
        ):
            return
        self._start_x_refresh(ids)

    def _start_x_refresh(self, sample_ids: list[int]) -> None:
        if self.refreshing:
            return
        self.refreshing = True
        self.single_refresh_button.configure(state="disabled")
        self.batch_refresh_button.configure(state="disabled")

        def work() -> None:
            try:
                count = TrainingPipeline(self.database_config, self.database).refresh_x_labels(
                    sample_ids=sample_ids,
                    confidence=0.70,
                )
                self.refresh_queue.put(("done", count))
            except Exception as exc:
                self.refresh_queue.put(("error", str(exc)))

        threading.Thread(target=work, name="x-label-refresh", daemon=True).start()
        self.after(100, self._poll_x_refresh)

    def _poll_x_refresh(self) -> None:
        try:
            kind, payload = self.refresh_queue.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(100, self._poll_x_refresh)
            return
        self.refreshing = False
        self.single_refresh_button.configure(state="normal")
        self.batch_refresh_button.configure(state="normal")
        if kind == "error":
            messagebox.showerror("X 標註刷新失敗", str(payload), parent=self)
            return
        self._resolved_paths.clear()
        self._refresh()
        messagebox.showinfo("X 標註刷新完成", f"已完成 {payload} 筆資料的 X 模型分析。", parent=self)

    def _show_selected(self, _event=None) -> None:
        row = self._selected_row()
        if row is None:
            return
        image_path = self._resolve_path(row["image_path"])
        metadata_path = self._resolve_path(row["metadata_path"])
        if image_path is None:
            original = Path(row["image_path"])
            self.preview.configure(
                text=f"影像遺失\n{original.name}\n請確認 production_data/training_captures 是否完整",
                image="",
            )
            self.path_var.set(str(original))
            return
        # cv2.imread 在 Windows 對含中文或其他非 ASCII 的完整路徑可能失敗；
        # 先由 Python 讀位元組，再交給 OpenCV 解碼可正常處理舊電腦路徑。
        try:
            frame_bytes = np.frombuffer(image_path.read_bytes(), dtype=np.uint8)
            frame = cv2.imdecode(frame_bytes, cv2.IMREAD_COLOR)
        except OSError:
            frame = None
        if frame is None:
            self.preview.configure(text=f"影像無法讀取：{image_path.name}", image="")
            return
        height, width = frame.shape[:2]
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path else {}
        except (OSError, json.JSONDecodeError):
            metadata = {"objects": []}
        for item in metadata.get("objects", []):
            x1, y1, x2, y2 = [int(value) for value in item.get("bbox_xyxy", [0, 0, 0, 0])]
            s_color = (255, 100, 0)
            line_width = max(3, min(width, height) // 350)
            cv2.rectangle(frame, (x1, y1), (x2, y2), s_color, line_width)
            cv2.putText(
                frame,
                f"S online {item.get('class_name', '?')} {float(item.get('confidence', 0)):.2f}",
                (x1, max(32, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                s_color,
                line_width,
            )

        x_labels_path = self._resolve_path(row["x_labels_path"])
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
                x_color = (0, 220, 0)
                line_width = max(3, min(width, height) // 350)
                cv2.rectangle(frame, (x1, y1), (x2, y2), x_color, line_width)
                cv2.putText(
                    frame,
                    f"X auto {class_names.get(class_id, class_id)}",
                    (x1, min(height - 12, y2 + 32)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    x_color,
                    line_width,
                )

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        available_width = max(700, self.preview.winfo_width() - 24)
        available_height = max(590, self.preview.winfo_height() - 24)
        image.thumbnail((available_width, available_height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self.preview_photo, text="")
        x_note = "有 X auto 自動標註" if x_labels_path else "無 X auto 候選（需重新執行模型自動標註）"
        self.path_var.set(f"藍色：S online 線上模型　綠色：X auto 自動標註　｜　{x_note}\n{image_path}")

    def _resolve_path(self, raw_path: str | None) -> Path | None:
        if not raw_path:
            return None
        if raw_path in self._resolved_paths:
            return self._resolved_paths[raw_path]
        original = Path(raw_path)
        if original.is_file():
            resolved = original
        else:
            matches = list(self.data_root.rglob(original.name))
            resolved = matches[0] if matches else None
        self._resolved_paths[raw_path] = resolved
        return resolved

    def _approve_x(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        x_labels_path = self._resolve_path(row["x_labels_path"])
        if x_labels_path is None:
            messagebox.showwarning("沒有 X 標註", "此資料尚無可接受的 x 候選標註。", parent=self)
            return
        next_index = self._next_index_after_selected()
        self.database.update_training_sample_review(
            row["id"], "APPROVED", "人工確認並接受 x 候選標註"
        )
        self._refresh_select(next_index)

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


class AnnotationEditorDialog(tk.Toplevel):
    """用滑鼠編輯一筆 YOLO 標註：新增、移動、縮放、刪除與分類。"""

    COLORS = {0: "#2563eb", 1: "#dc2626", 2: "#16a34a"}
    NAMES = {0: "normal", 1: "mold", 2: "small"}

    def __init__(self, parent, row, data_root, database, config, on_saved) -> None:
        super().__init__(parent)
        self.row = row
        self.data_root = Path(data_root).resolve()
        self.database = database
        self.config = config
        self.on_saved = on_saved
        self.title(f"編輯標註 - ID {row['id']}")
        self.geometry("1380x850")
        self.transient(parent)
        self.boxes: list[dict[str, float | int]] = []
        self.selected: int | None = None
        self.mode = None
        self.press = (0.0, 0.0)
        self.original_size = (1, 1)
        self.scale = 1.0
        self.photo = None
        self.pending_corner = None

        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="類別").pack(side="left")
        self.class_var = tk.StringVar(value="normal")
        self.class_combo = ttk.Combobox(
            toolbar, textvariable=self.class_var,
            values=("normal", "mold", "small"), state="readonly", width=10,
        )
        self.class_combo.pack(side="left", padx=6)
        self.class_combo.bind("<<ComboboxSelected>>", self._class_changed)
        ttk.Label(toolbar, text="新增框：依序點左上、右下；拖曳既有框可移動／縮放；右鍵/Delete 刪除").pack(
            side="left", padx=12
        )
        ttk.Button(toolbar, text="儲存標註", command=self._save).pack(side="right")
        ttk.Button(toolbar, text="加入X訓練集", command=self._save_for_x_training).pack(
            side="right", padx=8
        )
        ttk.Button(toolbar, text="取消", command=self.destroy).pack(side="right", padx=8)

        self.canvas = tk.Canvas(self, background="#202020", cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._delete_at)
        self.canvas.bind("<Delete>", self._delete_selected)
        self.canvas.focus_set()
        self._load()

    def _resolve(self, raw_path: str | None) -> Path | None:
        if not raw_path:
            return None
        path = Path(raw_path)
        if path.is_file():
            return path
        matches = list(self.data_root.rglob(path.name))
        return matches[0] if matches else None

    def _load(self) -> None:
        image_path = self._resolve(self.row["image_path"])
        if image_path is None:
            messagebox.showerror("無法編輯", "找不到原始影像。", parent=self)
            self.destroy()
            return
        try:
            image_data = np.frombuffer(image_path.read_bytes(), dtype=np.uint8)
            frame = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
        except OSError:
            frame = None
        if frame is None:
            messagebox.showerror("無法編輯", "原始影像無法解碼。", parent=self)
            self.destroy()
            return
        self.original_size = (frame.shape[1], frame.shape[0])
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((1300, 730), Image.Resampling.LANCZOS)
        self.scale = image.width / self.original_size[0]
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.configure(width=image.width, height=image.height)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw", tags="background")

        label_path = self._resolve(self.row["x_labels_path"])
        if label_path:
            for line in label_path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 5:
                    cls, xc, yc, w, h = int(parts[0]), *map(float, parts[1:])
                    self.boxes.append({"cls": cls, "x1": (xc - w / 2) * self.original_size[0],
                                       "y1": (yc - h / 2) * self.original_size[1],
                                       "x2": (xc + w / 2) * self.original_size[0],
                                       "y2": (yc + h / 2) * self.original_size[1]})
        else:
            metadata_path = self._resolve(self.row["metadata_path"])
            if metadata_path:
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    metadata = {}
                for item in metadata.get("objects", []):
                    x1, y1, x2, y2 = item.get("bbox_xyxy", [0, 0, 0, 0])
                    self.boxes.append({"cls": int(item.get("class_id", 0)), "x1": x1,
                                       "y1": y1, "x2": x2, "y2": y2})
        self._redraw()

    def _point(self, event):
        return event.x / self.scale, event.y / self.scale

    def _hit(self, x, y):
        for index in range(len(self.boxes) - 1, -1, -1):
            box = self.boxes[index]
            if box["x1"] <= x <= box["x2"] and box["y1"] <= y <= box["y2"]:
                return index
        return None

    def _press(self, event):
        self.canvas.focus_set()
        x, y = self._point(event)
        self.press = (x, y)
        hit = self._hit(x, y)
        self.selected = hit
        if hit is None:
            if self.pending_corner is None:
                self.pending_corner = (x, y)
                self.mode = "corner_pending"
            else:
                x1, y1 = self.pending_corner
                cls = {"normal": 0, "mold": 1, "small": 2}[self.class_var.get()]
                self.boxes.append({"cls": cls, "x1": x1, "y1": y1, "x2": x, "y2": y})
                self.selected = len(self.boxes) - 1
                self.pending_corner = None
                self.mode = None
        else:
            box = self.boxes[hit]
            self.class_var.set(self.NAMES.get(int(box["cls"]), "normal"))
            edge = 14 / self.scale
            near_x = abs(x - box["x1"]) < edge or abs(x - box["x2"]) < edge
            near_y = abs(y - box["y1"]) < edge or abs(y - box["y2"]) < edge
            self.mode = "resize" if near_x or near_y else "move"
            self.resize_x = "left" if abs(x - box["x1"]) < abs(x - box["x2"]) else "right"
            self.resize_y = "top" if abs(y - box["y1"]) < abs(y - box["y2"]) else "bottom"
            self.offset = (x - box["x1"], y - box["y1"])
        self._redraw()

    def _drag(self, event):
        if self.mode == "corner_pending":
            self._redraw()
            return
        if self.selected is None:
            return
        x, y = self._point(event)
        box = self.boxes[self.selected]
        if self.mode == "move":
            width, height = box["x2"] - box["x1"], box["y2"] - box["y1"]
            box["x1"], box["y1"] = x - self.offset[0], y - self.offset[1]
            box["x2"], box["y2"] = box["x1"] + width, box["y1"] + height
        else:
            if self.resize_x == "left":
                box["x1"] = x
            else:
                box["x2"] = x
            if self.resize_y == "top":
                box["y1"] = y
            else:
                box["y2"] = y
        self._redraw()

    def _class_changed(self, _event=None):
        if self.selected is not None:
            self.boxes[self.selected]["cls"] = {
                "normal": 0, "mold": 1, "small": 2
            }[self.class_var.get()]
            self._redraw()

    def _release(self, _event):
        if self.selected is not None and self.mode in {"move", "resize"}:
            box = self.boxes[self.selected]
            box["x1"], box["x2"] = sorted((box["x1"], box["x2"]))
            box["y1"], box["y2"] = sorted((box["y1"], box["y2"]))
            if box["x2"] - box["x1"] < 3 or box["y2"] - box["y1"] < 3:
                self._delete_selected()
        self.mode = None

    def _delete_at(self, event):
        self.selected = self._hit(*self._point(event))
        self._delete_selected()

    def _delete_selected(self, _event=None):
        if self.selected is not None and self.selected < len(self.boxes):
            self.boxes.pop(self.selected)
            self.selected = None
            self._redraw()

    def _redraw(self):
        self.canvas.delete("box")
        for index, box in enumerate(self.boxes):
            color = self.COLORS.get(int(box["cls"]), "#ffffff")
            coords = tuple(value * self.scale for value in (box["x1"], box["y1"], box["x2"], box["y2"]))
            width = 4 if index == self.selected else 2
            self.canvas.create_rectangle(*coords, outline=color, width=width, tags="box")
            self.canvas.create_text(coords[0] + 4, coords[1] + 4,
                                    text=f"{self.NAMES.get(int(box['cls']), '?')}",
                                    fill=color, anchor="nw", font=("Arial", 14, "bold"), tags="box")

    def _save(self):
        self._write_labels("NEEDS_MANUAL_LABEL", "人工編輯 X 標註")

    def _save_for_x_training(self):
        self._write_labels("X_TRAINING", "人工編輯並加入 X 模型訓練集")

    def _write_labels(self, status: str, reason: str):
        width, height = self.original_size
        output_root = self.config.training_root / "manual_labels"
        output_root.mkdir(parents=True, exist_ok=True)
        label_path = output_root / f"sample_{int(self.row['id']):08d}.txt"
        lines = []
        for box in self.boxes:
            x1, x2 = sorted((max(0, box["x1"]), min(width, box["x2"])))
            y1, y2 = sorted((max(0, box["y1"]), min(height, box["y2"])))
            lines.append(f"{int(box['cls'])} {(x1+x2)/(2*width):.8f} {(y1+y2)/(2*height):.8f} {(x2-x1)/width:.8f} {(y2-y1)/height:.8f}")
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self.database.set_training_sample_x_labels(
            int(self.row["id"]), label_path, f"{reason}，共 {len(lines)} 個框"
        )
        self.database.set_training_sample_review_status(int(self.row["id"]), status)
        self.on_saved()
        self.destroy()


def run_app() -> None:
    app = PeanutProductionApp()
    app.mainloop()
