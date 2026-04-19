import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

def setup_logging(settings_dir: Path) -> None:
    logs_dir = settings_dir.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    _purge_old_logs(logs_dir, days=2)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = logs_dir / f"edc_{timestamp}.log"

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)

def _purge_old_logs(logs_dir: Path, days: int) -> None:
    cutoff = time.time() - (days * 86400)
    for f in logs_dir.glob("edc_*.log"):
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except Exception:
                pass
