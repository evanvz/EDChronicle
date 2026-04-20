"""
Voice command listener — offline speech recognition via vosk.
Requires the trigger word "navigate" before a tab name to prevent false positives
from game audio or background speech. Fires immediately on recognition.
Post-switch mic blackout prevents TTS echo from re-triggering.
"""
import json
import logging
import queue
import time
import urllib.request
import zipfile
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)

TAB_PHRASES: dict[str, str] = {
    "overview":     "Overview",
    "hud":          "Overview",
    "exploration":  "Exploration",
    "exobiology":   "Exobiology",
    "biology":      "Exobiology",
    "powerplay":    "PowerPlay",
    "combat":       "Combat",
    "intel":        "Intel",
}

_TRIGGER_WORDS = {"which", "to"}

_VOCAB_WORDS = sorted({w for phrase in TAB_PHRASES for w in phrase.split()} | _TRIGGER_WORDS)
_GRAMMAR     = json.dumps(_VOCAB_WORDS + ["[unk]"])

MODEL_URL      = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_DIR_NAME = "vosk"

_POST_SWITCH_BLACKOUT = 3.0


def ensure_model(models_dir: Path) -> Path | None:
    model_path = models_dir / MODEL_DIR_NAME
    if model_path.exists():
        return model_path
    log.info("vosk model not found — downloading (~40 MB)...")
    zip_path = models_dir / "_vosk_model.zip"
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            top_dirs = {Path(name).parts[0] for name in zf.namelist()}
            zf.extractall(models_dir)
        zip_path.unlink(missing_ok=True)
        # Rename extracted folder to the expected MODEL_DIR_NAME
        for extracted in top_dirs:
            src = models_dir / extracted
            if src.exists() and src != model_path:
                src.rename(model_path)
                break
        log.info("vosk model ready at %s", model_path)
        return model_path
    except Exception as exc:
        log.error("vosk model download failed: %s", exc)
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


class VoiceCommandListener(QObject):
    """
    Say "which to [tab]" to switch tabs immediately.
    Both "which" and "to" must appear in the same utterance as the tab name.
    8-second mic blackout after each switch prevents TTS echo re-triggering.
    """

    command_detected = pyqtSignal(str)

    SAMPLE_RATE = 16000
    BLOCK_SIZE  = 8000

    def __init__(self, models_dir: Path):
        super().__init__()
        self._models_dir = models_dir
        self._running    = False

    def _clean(self, text: str) -> list[str]:
        return [w for w in text.lower().split() if w != "[unk]"]

    def _match(self, words: list[str]) -> str | None:
        word_set = set(words)
        if not _TRIGGER_WORDS.issubset(word_set):
            return None
        for word in words:
            if word in TAB_PHRASES:
                return TAB_PHRASES[word]
        return None

    @pyqtSlot()
    def run(self):
        try:
            from vosk import Model, KaldiRecognizer
        except ImportError:
            log.error("vosk not installed — voice commands unavailable. Run: pip install vosk")
            return

        model_path = ensure_model(self._models_dir)
        if not model_path:
            log.error("vosk model unavailable — voice commands disabled")
            return

        try:
            model = Model(str(model_path))
            rec   = KaldiRecognizer(model, self.SAMPLE_RATE, _GRAMMAR)
        except Exception as exc:
            log.error("vosk init failed: %s", exc)
            return

        self._running    = True
        blackout_until   = 0.0
        log.info("Voice command listener active — say 'which to [tab]' to switch tabs")

        audio_q: queue.Queue = queue.Queue()

        def _audio_cb(indata, frames, time_info, status):
            if self._running:
                audio_q.put(bytes(indata))

        try:
            import sounddevice as sd
            with sd.RawInputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=self.BLOCK_SIZE,
                dtype="int16",
                channels=1,
                callback=_audio_cb,
            ):
                while self._running:
                    try:
                        data = audio_q.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    if not rec.AcceptWaveform(data):
                        continue

                    result = json.loads(rec.Result())
                    words  = self._clean(result.get("text", ""))
                    if not words:
                        continue

                    now = time.monotonic()
                    if now < blackout_until:
                        log.debug("Blackout active — ignoring: %s", words)
                        continue

                    tab = self._match(words)
                    if not tab:
                        continue

                    log.debug("Voice command: %s → %s", words, tab)
                    self.command_detected.emit(tab)
                    blackout_until = now + _POST_SWITCH_BLACKOUT

        except Exception as exc:
            log.error("Voice command listener error: %s", exc)

        log.debug("Voice command listener stopped")

    def stop(self):
        self._running = False
