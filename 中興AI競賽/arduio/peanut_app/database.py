from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from .domain import Anomaly, PeanutRecord, ProductionStats, Severity, WorkOrder, WorkOrderInput


MONTH_CODES = "ABCDEFGHIJKL"


class ProductionDatabase:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_order_no TEXT NOT NULL UNIQUE,
                    supplier_name TEXT NOT NULL,
                    vendor_code TEXT NOT NULL,
                    variety_code TEXT NOT NULL,
                    material_lot TEXT NOT NULL,
                    material_manufacture_date TEXT NOT NULL,
                    target_weight_g REAL NOT NULL CHECK(target_weight_g > 0),
                    production_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'STOPPED'
                );

                CREATE TABLE IF NOT EXISTS peanuts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
                    sequence_no INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    detected_at TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    confidence_center REAL NOT NULL,
                    confidence_mean REAL NOT NULL,
                    valid_frames INTEGER NOT NULL,
                    class_counts_json TEXT NOT NULL,
                    area_mean_px2 REAL NOT NULL,
                    weight_est_g REAL,
                    lane INTEGER NOT NULL,
                    boundary_between_json TEXT,
                    eject_lanes_json TEXT NOT NULL,
                    predicted_false_reject INTEGER NOT NULL DEFAULT 0,
                    model_version TEXT NOT NULL,
                    model_hash TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    session_token TEXT NOT NULL,
                    center_frame_number INTEGER NOT NULL,
                    center_time_seconds REAL NOT NULL,
                    command_due_time_seconds REAL,
                    mean_width_px REAL NOT NULL,
                    speed_px_per_frame REAL NOT NULL,
                    record_status TEXT NOT NULL DEFAULT 'COMPLETE',
                    UNIQUE(work_order_id, sequence_no)
                );

                CREATE INDEX IF NOT EXISTS idx_peanuts_work_order
                    ON peanuts(work_order_id);
                CREATE INDEX IF NOT EXISTS idx_peanuts_track
                    ON peanuts(work_order_id, track_id);

                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_order_id INTEGER REFERENCES work_orders(id),
                    code TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    cleared_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_anomalies_active
                    ON anomalies(cleared_at, work_order_id);

                CREATE TABLE IF NOT EXISTS model_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL UNIQUE,
                    weight_path TEXT NOT NULL,
                    weight_hash TEXT NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS training_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    x_model_path TEXT NOT NULL,
                    s_model_path TEXT NOT NULL,
                    dataset_path TEXT,
                    output_path TEXT,
                    message TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS training_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
                    session_token TEXT NOT NULL,
                    frame_number INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    metadata_path TEXT NOT NULL,
                    x_labels_path TEXT,
                    review_status TEXT NOT NULL DEFAULT 'CAPTURED',
                    review_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(work_order_id, session_token, frame_number)
                );

                CREATE INDEX IF NOT EXISTS idx_training_samples_review
                    ON training_samples(review_status, work_order_id);

                CREATE TABLE IF NOT EXISTS model_activations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_version_id INTEGER NOT NULL REFERENCES model_versions(id),
                    activated_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                """
            )
            peanut_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(peanuts)").fetchall()
            }
            if "record_status" not in peanut_columns:
                connection.execute(
                    "ALTER TABLE peanuts ADD COLUMN record_status TEXT NOT NULL DEFAULT 'COMPLETE'"
                )
            if "session_token" not in peanut_columns:
                connection.execute(
                    "ALTER TABLE peanuts ADD COLUMN session_token TEXT NOT NULL DEFAULT 'legacy'"
                )
            training_sample_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(training_samples)").fetchall()
            }
            if "session_token" not in training_sample_columns:
                connection.execute(
                    """
                    ALTER TABLE training_samples
                    ADD COLUMN session_token TEXT NOT NULL DEFAULT 'legacy'
                    """
                )

    @staticmethod
    def _row_to_work_order(row: sqlite3.Row | None) -> WorkOrder | None:
        if row is None:
            return None
        return WorkOrder(**dict(row))

    def create_work_order(self, values: WorkOrderInput, production_day: date | None = None) -> WorkOrder:
        production_day = production_day or date.today()
        prefix = (
            f"{production_day.year % 100:02d}"
            f"{MONTH_CODES[production_day.month - 1]}"
            f"{production_day.day:02d}-"
            f"{values.vendor_code}-{values.variety_code}"
        )
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM work_orders WHERE work_order_no LIKE ?",
                (f"{prefix}-%",),
            ).fetchone()
            sequence = int(row["count"]) + 1
            work_order_no = f"{prefix}-{sequence:03d}"
            now = datetime.now().isoformat(timespec="seconds")
            cursor = connection.execute(
                """
                INSERT INTO work_orders (
                    work_order_no, supplier_name, vendor_code, variety_code,
                    material_lot, material_manufacture_date, target_weight_g,
                    production_date, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'STOPPED')
                """,
                (
                    work_order_no,
                    "",  # 舊資料庫相容欄位；新版只使用廠商編號。
                    values.vendor_code,
                    values.variety_code,
                    values.material_lot,
                    values.material_manufacture_date,
                    values.target_weight_g,
                    production_day.isoformat(),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM work_orders WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        work_order = self._row_to_work_order(row)
        if work_order is None:
            raise RuntimeError("建立工單後無法讀回資料")
        return work_order

    def latest_work_order(self) -> WorkOrder | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_orders ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return self._row_to_work_order(row)

    def get_work_order(self, work_order_id: int) -> WorkOrder | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_orders WHERE id = ?", (work_order_id,)
            ).fetchone()
        return self._row_to_work_order(row)

    def set_work_order_status(self, work_order_id: int, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE work_orders SET status = ? WHERE id = ?",
                (status, work_order_id),
            )

    def next_peanut_sequence(self, work_order_id: int) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence_no), 0) + 1 AS next_no "
                "FROM peanuts WHERE work_order_id = ?",
                (work_order_id,),
            ).fetchone()
        return int(row["next_no"])

    def insert_peanut(self, record: PeanutRecord) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO peanuts (
                    work_order_id, sequence_no, track_id, detected_at,
                    classification, confidence_center, confidence_mean,
                    valid_frames, class_counts_json, area_mean_px2,
                    weight_est_g, lane, boundary_between_json, eject_lanes_json,
                    predicted_false_reject, model_version, model_hash, image_path,
                    session_token, center_frame_number, center_time_seconds,
                    command_due_time_seconds, mean_width_px, speed_px_per_frame,
                    record_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.work_order_id,
                    record.sequence_no,
                    record.track_id,
                    record.detected_at,
                    record.classification,
                    record.confidence_center,
                    record.confidence_mean,
                    record.valid_frames,
                    json.dumps(record.class_counts, ensure_ascii=False),
                    record.area_mean_px2,
                    record.weight_est_g,
                    record.lane,
                    json.dumps(record.boundary_between) if record.boundary_between else None,
                    json.dumps(record.eject_lanes),
                    int(record.predicted_false_reject),
                    record.model_version,
                    record.model_hash,
                    str(record.image_path),
                    record.session_token,
                    record.center_frame_number,
                    record.center_time_seconds,
                    record.command_due_time_seconds,
                    record.mean_width_px,
                    record.speed_px_per_frame,
                    record.record_status,
                ),
            )
            return int(cursor.lastrowid)

    def mark_false_reject(self, peanut_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE peanuts SET predicted_false_reject = 1
                WHERE id = ? AND classification = 'normal'
                  AND predicted_false_reject = 0
                """,
                (peanut_id,),
            )
            return cursor.rowcount > 0

    def stats(self, work_order_id: int) -> ProductionStats:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN classification = 'normal' THEN 1 ELSE 0 END) AS normal,
                    SUM(CASE WHEN classification = 'mold' THEN 1 ELSE 0 END) AS mold,
                    SUM(CASE WHEN classification = 'small' THEN 1 ELSE 0 END) AS small,
                    SUM(CASE WHEN classification = 'unknown' THEN 1 ELSE 0 END) AS unknown,
                    COALESCE(SUM(weight_est_g), 0) AS total_weight_g,
                    SUM(CASE WHEN weight_est_g IS NOT NULL THEN 1 ELSE 0 END) AS weighted_count,
                    SUM(CASE WHEN predicted_false_reject = 1 THEN 1 ELSE 0 END)
                        AS predicted_false_rejects
                FROM peanuts WHERE work_order_id = ?
                """,
                (work_order_id,),
            ).fetchone()
        return ProductionStats(
            normal=int(row["normal"] or 0),
            mold=int(row["mold"] or 0),
            small=int(row["small"] or 0),
            unknown=int(row["unknown"] or 0),
            total_weight_g=float(row["total_weight_g"] or 0.0),
            weighted_count=int(row["weighted_count"] or 0),
            predicted_false_rejects=int(row["predicted_false_rejects"] or 0),
        )

    def add_anomaly(
        self,
        code: str,
        message: str,
        severity: Severity = Severity.WARNING,
        work_order_id: int | None = None,
        deduplicate_active: bool = True,
    ) -> int:
        with self.connect() as connection:
            if deduplicate_active:
                row = connection.execute(
                    """
                    SELECT id FROM anomalies
                    WHERE code = ? AND cleared_at IS NULL
                      AND (work_order_id = ? OR (work_order_id IS NULL AND ? IS NULL))
                    ORDER BY id DESC LIMIT 1
                    """,
                    (code, work_order_id, work_order_id),
                ).fetchone()
                if row is not None:
                    return int(row["id"])
            cursor = connection.execute(
                """
                INSERT INTO anomalies (
                    work_order_id, code, severity, message, created_at, cleared_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    work_order_id,
                    code,
                    severity.value,
                    message,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            return int(cursor.lastrowid)

    def list_anomalies(
        self, work_order_id: int | None = None, active_only: bool = False
    ) -> list[Anomaly]:
        clauses: list[str] = []
        parameters: list[object] = []
        if work_order_id is not None:
            clauses.append("work_order_id = ?")
            parameters.append(work_order_id)
        if active_only:
            clauses.append("cleared_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM anomalies {where} ORDER BY id DESC", parameters
            ).fetchall()
        return [Anomaly(**dict(row)) for row in rows]

    def clear_anomaly(self, anomaly_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE anomalies SET cleared_at = ? WHERE id = ? AND cleared_at IS NULL",
                (datetime.now().isoformat(timespec="seconds"), anomaly_id),
            )

    def has_active_critical_anomaly(self, work_order_id: int | None) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM anomalies
                WHERE cleared_at IS NULL AND severity = 'CRITICAL'
                  AND (work_order_id = ? OR work_order_id IS NULL)
                LIMIT 1
                """,
                (work_order_id,),
            ).fetchone()
        return row is not None

    def summary_rows(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT
                    w.vendor_code,
                    w.variety_code,
                    substr(w.production_date, 1, 7) AS production_month,
                    COUNT(p.id) AS total,
                    SUM(CASE WHEN p.classification IN ('mold', 'small') THEN 1 ELSE 0 END) AS ng,
                    AVG(p.weight_est_g) AS avg_weight_g,
                    AVG(p.confidence_mean) AS avg_confidence
                FROM work_orders w
                LEFT JOIN peanuts p ON p.work_order_id = w.id
                GROUP BY w.vendor_code, w.variety_code, production_month
                ORDER BY production_month DESC, total DESC
                """
            ).fetchall()

    def create_training_run(self, x_model_path: Path, s_model_path: Path) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO training_runs (
                    status, x_model_path, s_model_path, started_at
                ) VALUES ('QUEUED', ?, ?, ?)
                """,
                (
                    str(x_model_path),
                    str(s_model_path),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            return int(cursor.lastrowid)

    def register_model_version(
        self,
        version: str,
        weight_path: Path,
        weight_hash: str,
        metrics: dict[str, float],
        active: bool = False,
    ) -> None:
        with self.connect() as connection:
            if active:
                connection.execute("UPDATE model_versions SET is_active = 0")
            connection.execute(
                """
                INSERT INTO model_versions (
                    version, weight_path, weight_hash, metrics_json,
                    created_at, activated_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version) DO UPDATE SET
                    weight_path = excluded.weight_path,
                    weight_hash = excluded.weight_hash,
                    metrics_json = excluded.metrics_json,
                    activated_at = CASE
                        WHEN excluded.is_active = 1 THEN excluded.activated_at
                        ELSE model_versions.activated_at
                    END,
                    is_active = CASE
                        WHEN excluded.is_active = 1 THEN 1
                        ELSE model_versions.is_active
                    END
                """,
                (
                    version,
                    str(weight_path),
                    weight_hash,
                    json.dumps(metrics, ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                    datetime.now().isoformat(timespec="seconds") if active else None,
                    int(active),
                ),
            )

    def ensure_initial_model(
        self, version: str, weight_path: Path, weight_hash: str
    ) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM model_versions WHERE is_active = 1 LIMIT 1"
            ).fetchone()
        if row is None:
            self.register_model_version(
                version=version,
                weight_path=weight_path,
                weight_hash=weight_hash,
                metrics={},
                active=True,
            )
            with self.connect() as connection:
                model_row = connection.execute(
                    "SELECT id FROM model_versions WHERE version = ?", (version,)
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO model_activations (model_version_id, activated_at, reason)
                    VALUES (?, ?, 'INITIAL_MODEL')
                    """,
                    (model_row["id"], datetime.now().isoformat(timespec="seconds")),
                )

    def activate_model(self, version: str, reason: str) -> None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, weight_path FROM model_versions WHERE version = ?", (version,)
            ).fetchone()
            if row is None:
                raise ValueError(f"找不到模型版本：{version}")
            if not Path(row["weight_path"]).exists():
                raise FileNotFoundError(f"模型權重已不存在：{row['weight_path']}")
            now = datetime.now().isoformat(timespec="seconds")
            connection.execute("UPDATE model_versions SET is_active = 0")
            connection.execute(
                """
                UPDATE model_versions SET is_active = 1, activated_at = ?
                WHERE id = ?
                """,
                (now, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO model_activations (model_version_id, activated_at, reason)
                VALUES (?, ?, ?)
                """,
                (row["id"], now, reason),
            )

    def active_model(self) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT version, weight_path, weight_hash, metrics_json
                FROM model_versions WHERE is_active = 1
                ORDER BY activated_at DESC LIMIT 1
                """
            ).fetchone()

    def model_version_rows(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT version, weight_path, weight_hash, metrics_json,
                       created_at, activated_at, is_active
                FROM model_versions ORDER BY id DESC
                """
            ).fetchall()

    def upsert_training_sample(
        self,
        work_order_id: int,
        session_token: str,
        frame_number: int,
        image_path: Path,
        metadata_path: Path,
        review_status: str,
        review_reason: str,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        priority = {
            "CAPTURED": 0,
            "AUTO_CANDIDATE": 1,
            "APPROVED": 2,
            "NEEDS_REVIEW": 3,
            "NEEDS_MANUAL_LABEL": 4,
        }
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, review_status FROM training_samples
                WHERE work_order_id = ? AND session_token = ? AND frame_number = ?
                """,
                (work_order_id, session_token, frame_number),
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO training_samples (
                        work_order_id, session_token, frame_number, image_path, metadata_path,
                        review_status, review_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        work_order_id,
                        session_token,
                        frame_number,
                        str(image_path),
                        str(metadata_path),
                        review_status,
                        review_reason,
                        now,
                        now,
                    ),
                )
                return int(cursor.lastrowid)
            current_status = str(row["review_status"])
            selected_status = (
                review_status
                if priority.get(review_status, 0) > priority.get(current_status, 0)
                else current_status
            )
            connection.execute(
                """
                UPDATE training_samples
                SET image_path = ?, metadata_path = ?, review_status = ?,
                    review_reason = CASE WHEN ? != '' THEN ? ELSE review_reason END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(image_path),
                    str(metadata_path),
                    selected_status,
                    review_reason,
                    review_reason,
                    now,
                    row["id"],
                ),
            )
            return int(row["id"])

    def training_sample_rows(self, statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
        parameters: list[str] = []
        where = ""
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where = f"WHERE ts.review_status IN ({placeholders})"
            parameters.extend(statuses)
        with self.connect() as connection:
            return connection.execute(
                f"""
                SELECT ts.*, w.work_order_no, w.material_lot
                FROM training_samples ts
                JOIN work_orders w ON w.id = ts.work_order_id
                {where}
                ORDER BY ts.id DESC
                """,
                parameters,
            ).fetchall()

    def update_training_sample_review(
        self,
        sample_id: int,
        status: str,
        reason: str,
        x_labels_path: Path | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE training_samples
                SET review_status = ?, review_reason = ?,
                    x_labels_path = COALESCE(?, x_labels_path), updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    reason,
                    str(x_labels_path) if x_labels_path else None,
                    datetime.now().isoformat(timespec="seconds"),
                    sample_id,
                ),
            )

    def update_training_run(
        self,
        run_id: int,
        status: str,
        message: str = "",
        dataset_path: Path | None = None,
        output_path: Path | None = None,
        finished: bool = False,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE training_runs
                SET status = ?, message = ?,
                    dataset_path = COALESCE(?, dataset_path),
                    output_path = COALESCE(?, output_path),
                    finished_at = CASE WHEN ? THEN ? ELSE finished_at END
                WHERE id = ?
                """,
                (
                    status,
                    message,
                    str(dataset_path) if dataset_path else None,
                    str(output_path) if output_path else None,
                    int(finished),
                    datetime.now().isoformat(timespec="seconds"),
                    run_id,
                ),
            )
