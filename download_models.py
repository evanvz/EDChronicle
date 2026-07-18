"""
Downloads and extracts offline models needed by EDChronicle at install time,
so they're always present on first launch rather than lazily downloaded
during the app's first use of voice commands.

Run via install.bat after dependencies are installed.
"""
import sys
import zipfile
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
MODELS_DIR = APP_DIR / "models"

VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip"
VOSK_MODEL_DIR_NAME = "vosk"


def _download_with_progress(url: str, dest: Path):
    last_pct = -1

    def _report(block_num, block_size, total_size):
        nonlocal last_pct
        if total_size <= 0:
            return
        done = block_num * block_size
        pct = min(100, done * 100 // total_size)
        if pct != last_pct and pct % 10 == 0:
            print(f"  downloading... {pct}%")
            last_pct = pct
    urllib.request.urlretrieve(url, dest, reporthook=_report)


def ensure_vosk_model() -> bool:
    model_dir = MODELS_DIR / VOSK_MODEL_DIR_NAME
    if model_dir.exists() and any(model_dir.iterdir()):
        print(f"[voice commands] Vosk model already present at {model_dir}")
        return True

    print("[voice commands] Downloading Vosk speech recognition model (~128 MB)...")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = MODELS_DIR / "_vosk_model.zip"
    try:
        _download_with_progress(VOSK_MODEL_URL, zip_path)
        print("[voice commands] Extracting...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            top_dirs = {Path(name).parts[0] for name in zf.namelist()}
            zf.extractall(MODELS_DIR)
        zip_path.unlink(missing_ok=True)
        for extracted in top_dirs:
            src = MODELS_DIR / extracted
            if src.exists() and src != model_dir:
                src.rename(model_dir)
                break
    except Exception as exc:
        print(f"[voice commands] ERROR: model download failed: {exc}")
        zip_path.unlink(missing_ok=True)
        return False

    if not model_dir.exists() or not any(model_dir.iterdir()):
        print("[voice commands] ERROR: model extraction incomplete")
        return False

    print(f"[voice commands] Vosk model ready at {model_dir}")
    return True


if __name__ == "__main__":
    ok = ensure_vosk_model()
    sys.exit(0 if ok else 1)
