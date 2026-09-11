"""花生 AI 生產管理 GUI 啟動程式。"""

import os
from pathlib import Path

from peanut_app.gui import run_app


if __name__ == "__main__":
    # VS Code may launch with its installation directory as cwd. Ultralytics
    # resolves its AMP check weight (yolo26n.pt) relative to cwd.
    os.chdir(Path(__file__).resolve().parent)
    run_app()
