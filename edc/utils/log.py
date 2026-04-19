import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

def setup_logging(settings_dir: Path) -> None:
    settings_dir.mkdir(parents=True, exist_ok=True)

    _purge_old_logs(settings_dir, days=2)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = settings_dir / f"edc_{timestamp}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        handlers=[file_handler],
    )

def _purge_old_logs(settings_dir: Path, days: int) -> None:
    cutoff = time.time() - (days * 86400)
    for f in settings_dir.glob("edc_*.log"):
        if f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except Exception:
                pass
