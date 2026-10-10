# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""
Downloads and extracts offline models needed by EDChronicle at install time,
so they're always present on first launch rather than lazily downloaded
during the app's first use of voice commands.

Run via install.bat after dependencies are installed.
"""
import hashlib
import sys
import zipfile
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
MODELS_DIR = APP_DIR / "models"

# Each file is fetched from its original source first, then from our own copy
# (github.com/evanvz/EDChronicle-models), and must match its SHA-256 either way.
MIRROR = "https://github.com/evanvz/EDChronicle-models/releases/download/"

VOSK_MODEL_DIR_NAME = "vosk"
VOSK_ZIP = "vosk-model-en-us-0.22-lgraph.zip"
VOSK_URLS = (
    "https://alphacephei.com/vosk/models/" + VOSK_ZIP,
    MIRROR + "vosk-en-us-0.22-lgraph/" + VOSK_ZIP,
)
# Same value as edc/audio/voice_commands.MODEL_SHA256 (not imported: that module needs PyQt6).
VOSK_SHA256 = "d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334"

KOKORO_DIR_NAME = "kokoro"
KOKORO_SOURCES = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/",
    MIRROR + "kokoro-v1.0/",
)
KOKORO_FILES = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}


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


def _fetch(urls, dest: Path, sha256: str, tag: str) -> bool:
    """Download dest from the first url that works and matches sha256."""
    for url in urls:
        print(f"{tag} from {url}")
        try:
            _download_with_progress(url, dest)
        except Exception as exc:
            print(f"{tag} WARNING: download failed: {exc}")
            continue
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() == sha256:
            return True
        print(f"{tag} WARNING: checksum mismatch, file rejected")
    dest.unlink(missing_ok=True)
    print(f"{tag} ERROR: no source worked")
    return False


def ensure_vosk_model() -> bool:
    tag = "[voice commands]"
    model_dir = MODELS_DIR / VOSK_MODEL_DIR_NAME
    if model_dir.exists() and any(model_dir.iterdir()):
        print(f"{tag} Vosk model already present at {model_dir}")
        return True

    print(f"{tag} Downloading Vosk speech recognition model (~128 MB)...")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = MODELS_DIR / "_vosk_model.zip"
    if not _fetch(VOSK_URLS, zip_path, VOSK_SHA256, tag):
        return False
    try:
        print(f"{tag} Extracting...")
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
        print(f"{tag} ERROR: extraction failed: {exc}")
        zip_path.unlink(missing_ok=True)
        return False

    if not model_dir.exists() or not any(model_dir.iterdir()):
        print(f"{tag} ERROR: model extraction incomplete")
        return False

    print(f"{tag} Vosk model ready at {model_dir}")
    return True


def ensure_kokoro_model() -> bool:
    """Offline neural TTS voices (Kokoro), the app's speech engine."""
    tag = "[tts]"
    model_dir = MODELS_DIR / KOKORO_DIR_NAME
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, sha256 in KOKORO_FILES.items():
        dest = model_dir / name
        if dest.exists():
            continue
        print(f"{tag} Downloading Kokoro {name}...")
        tmp = dest.with_suffix(dest.suffix + ".part")
        if not _fetch([base + name for base in KOKORO_SOURCES], tmp, sha256, tag):
            return False
        tmp.rename(dest)
    print(f"{tag} Kokoro model ready at {model_dir}")
    return True


if __name__ == "__main__":
    vosk_ok = ensure_vosk_model()
    kokoro_ok = ensure_kokoro_model()
    sys.exit(0 if vosk_ok and kokoro_ok else 1)
