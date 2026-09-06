from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk


REPOSITORY_URL = "https://github.com/CJ1219/peanut-picking-machine"
ALLOWED_ORIGIN_URLS = {
    REPOSITORY_URL,
    REPOSITORY_URL + ".git",
    "git@github.com:CJ1219/peanut-picking-machine.git",
}
PLACEHOLDERS = (
    Path("production_data/.gitkeep"),
    Path("中興AI競賽/dataset/.gitkeep"),
    Path("中興AI競賽/dataset_sharpen/.gitkeep"),
    Path("中興AI競賽/runs/.gitkeep"),
)


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class GitHubBackupApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.root_path = application_root()
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.title("花生機 GitHub 自動備份")
        self.geometry("760x540")
        self.minsize(680, 460)

        main = ttk.Frame(self, padding=18)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="花生機 GitHub 自動備份", font=("Microsoft JhengHei UI", 17, "bold")).pack(anchor="w")
        ttk.Label(main, text=f"專案：{self.root_path}", wraplength=700).pack(anchor="w", pady=(8, 2))
        ttk.Label(main, text=f"目的地：{REPOSITORY_URL}（main）", wraplength=700).pack(anchor="w")

        note = (
            "會上傳程式碼、Arduino 韌體、測試與說明文件。模型、資料集、生產資料、"
            "影片、.venv、ZIP 與快取依 .gitignore 排除；四個備份路徑只保留 .gitkeep。"
        )
        ttk.Label(main, text=note, foreground="#8a5a00", wraplength=700).pack(anchor="w", pady=12)

        actions = ttk.Frame(main)
        actions.pack(fill="x")
        self.backup_button = ttk.Button(actions, text="立即上傳到 GitHub", command=self.start_backup)
        self.backup_button.pack(side="left")
        ttk.Button(actions, text="關閉", command=self.destroy).pack(side="right")

        self.status_var = tk.StringVar(value="準備完成")
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w", pady=(12, 4))
        self.log = tk.Text(main, wrap="word", font=("Consolas", 10), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.after(100, self.poll_messages)

    def write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run_git(self, *args: str, allow_no_changes: bool = False) -> str:
        command = ["git", *args]
        self.messages.put(("log", "> " + " ".join(command)))
        completed = subprocess.run(
            command,
            cwd=self.root_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        if output:
            self.messages.put(("log", output))
        if completed.returncode != 0 and not allow_no_changes:
            raise RuntimeError(output or f"Git 指令失敗：{' '.join(args)}")
        return output

    def start_backup(self) -> None:
        self.backup_button.configure(state="disabled")
        self.status_var.set("正在備份……")
        self.write_log(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 開始")
        threading.Thread(target=self.backup, name="github-backup", daemon=True).start()

    def backup(self) -> None:
        try:
            if shutil.which("git") is None:
                raise RuntimeError("找不到 Git，請先安裝 Git for Windows。")
            if not (self.root_path / ".git").is_dir():
                raise RuntimeError(f"{self.root_path} 不是 Git 專案。請把 EXE 放在花生機code根目錄。")

            origin_url = self.run_git("remote", "get-url", "origin").strip()
            if origin_url not in ALLOWED_ORIGIN_URLS:
                raise RuntimeError(
                    "Git 遠端位置不符，已停止上傳。\n"
                    f"目前：{origin_url}\n預期：{REPOSITORY_URL}"
                )

            for relative_path in PLACEHOLDERS:
                path = self.root_path / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text("# Backup directory placeholder.\n", encoding="utf-8")

            self.run_git("add", "-A")
            status = self.run_git("status", "--porcelain")
            if status.strip():
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.run_git("commit", "-m", f"Automatic backup {stamp}")
            else:
                self.messages.put(("log", "沒有程式碼變更，略過提交。"))
            self.run_git("push", "origin", "HEAD:main")
            self.messages.put(("done", "GitHub 備份完成"))
        except Exception as exc:
            self.messages.put(("error", str(exc)))

    def poll_messages(self) -> None:
        try:
            while True:
                kind, text = self.messages.get_nowait()
                if kind == "log":
                    self.write_log(text)
                elif kind == "done":
                    self.status_var.set(text)
                    self.write_log(text)
                    self.backup_button.configure(state="normal")
                    messagebox.showinfo("備份完成", text, parent=self)
                elif kind == "error":
                    self.status_var.set("備份失敗")
                    self.write_log("錯誤：" + text)
                    self.backup_button.configure(state="normal")
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self.poll_messages)


if __name__ == "__main__":
    GitHubBackupApp().mainloop()
