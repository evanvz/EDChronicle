"""
Voice command listener — offline speech recognition via Vosk.

Two command domains:

  App navigation  — "which to [tab]" switches the active panel
  Ship commands   — "[trigger] [phrase]" fires an in-game action

Both share a single Vosk recogniser with a combined grammar built from all
active phrases.  Post-action mic blackout prevents TTS echo re-triggering.
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

# ── App navigation ─────────────────────────────────────────────────────────────

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

_NAV_TRIGGER_WORDS = {"which", "to"}

# ── Vosk model ────────────────────────────────────────────────────────────────

MODEL_URL      = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_DIR_NAME = "vosk"

_POST_ACTION_BLACKOUT = 3.0


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
    Listens for voice commands and emits signals for both domains.

    App navigation:  say "which to [tab]"
    Ship commands:   say "[trigger_word] [phrase]"  e.g. "ship boost"

    Call update_ship_commands() whenever the command list or trigger word changes.
    """

    command_detected      = pyqtSignal(str)   # tab name for app navigation
    ship_command_detected = pyqtSignal(str)   # phrase for ship commands

    SAMPLE_RATE = 16000
    BLOCK_SIZE  = 8000

    def __init__(self, models_dir: Path):
        super().__init__()
        self._models_dir    = models_dir
        self._running       = False
        self._trigger_word  = "ship"
        self._ship_commands: list[dict] = []   # list of {phrase, _binding, repeat}
        self._grammar_json  = self._build_grammar()

    # ── Public config API ─────────────────────────────────────────────────────

    def update_ship_commands(self, commands: list[dict], trigger_word: str = "ship"):
        """Called from main thread whenever voice_commands.json changes."""
        self._ship_commands = commands
        self._trigger_word  = trigger_word.lower().strip() or "ship"
        self._grammar_json  = self._build_grammar()
        log.info("Ship commands updated: %d active, trigger='%s'",
                 len(commands), self._trigger_word)

    # ── Grammar ───────────────────────────────────────────────────────────────

    def _build_grammar(self) -> str:
        words: set[str] = set()
        # Navigation words
        words.update(TAB_PHRASES.keys())
        words.update(_NAV_TRIGGER_WORDS)
        # Ship trigger + all phrase words
        words.add(self._trigger_word)
        for cmd in self._ship_commands:
            for w in cmd.get("phrase", "").lower().split():
                words.add(w)
        vocab = sorted(words) + ["[unk]"]
        return json.dumps(vocab)

    # ── Matching ──────────────────────────────────────────────────────────────

    def _clean(self, text: str) -> list[str]:
        return [w for w in text.lower().split() if w != "[unk]"]

    def _match_nav(self, words: list[str]) -> str | None:
        word_set = set(words)
        if not _NAV_TRIGGER_WORDS.issubset(word_set):
            return None
        for word in words:
            if word in TAB_PHRASES:
                return TAB_PHRASES[word]
        return None

    def _match_ship(self, words: list[str]) -> dict | None:
        if self._trigger_word not in words:
            return None
        # Words after the trigger
        try:
            idx = words.index(self._trigger_word)
            tail = words[idx + 1:]
        except ValueError:
            return None
        if not tail:
            return None
        tail_str = " ".join(tail)
        # Exact phrase match first
        for cmd in self._ship_commands:
            if cmd.get("phrase", "").lower() == tail_str:
                return cmd
        # Partial: all phrase words present in tail
        for cmd in self._ship_commands:
            phrase_words = set(cmd.get("phrase", "").lower().split())
            if phrase_words and phrase_words.issubset(set(tail)):
                return cmd
        return None

    # ── Main loop ─────────────────────────────────────────────────────────────

    @pyqtSlot()
    def run(self):
        try:
            from vosk import Model, KaldiRecognizer
        except ImportError:
            log.error("vosk not installed — voice commands unavailable")
            return

        model_path = ensure_model(self._models_dir)
        if not model_path:
            log.error("vosk model unavailable — voice commands disabled")
            return

        try:
            model = Model(str(model_path))
        except Exception as exc:
            log.error("vosk model init failed: %s", exc)
            return

        self._running  = True
        blackout_until = 0.0
        log.info("Voice command listener active — trigger='%s', %d ship commands",
                 self._trigger_word, len(self._ship_commands))

        try:
            import miniaudio

            audio_q: queue.Queue = queue.Queue()

            while self._running:
                # Rebuild recogniser each loop so grammar picks up any updates
                try:
                    rec = KaldiRecognizer(model, self.SAMPLE_RATE, self._grammar_json)
                except Exception as exc:
                    log.error("KaldiRecognizer init failed: %s", exc)
                    break

                def _capture_gen():
                    received = yield b""
                    while self._running:
                        try:
                            if received:
                                audio_q.put(bytes(received))
                        except Exception:
                            pass
                        try:
                            received = yield
                        except Exception:
                            return

                gen = _capture_gen()
                next(gen)

                try:
                    device = miniaudio.CaptureDevice(
                        input_format=miniaudio.SampleFormat.SIGNED16,
                        nchannels=1,
                        sample_rate=self.SAMPLE_RATE,
                        buffersize_msec=int(self.BLOCK_SIZE / self.SAMPLE_RATE * 1000),
                    )
                    device.start(gen)
                except Exception as exc:
                    log.warning("Voice capture device unavailable, retrying in 3s: %s", exc)
                    time.sleep(3)
                    continue

                try:
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

                        # Try ship command first
                        ship_cmd = self._match_ship(words)
                        if ship_cmd:
                            phrase = ship_cmd.get("phrase", "")
                            log.debug("Ship command: %s → %s", words, phrase)
                            self.ship_command_detected.emit(phrase)
                            blackout_until = now + _POST_ACTION_BLACKOUT
                            continue

                        # Try app navigation
                        tab = self._match_nav(words)
                        if tab:
                            log.debug("Nav command: %s → %s", words, tab)
                            self.command_detected.emit(tab)
                            blackout_until = now + _POST_ACTION_BLACKOUT

                except Exception as exc:
                    log.warning("Voice capture error, restarting in 3s: %s", exc)
                    time.sleep(3)
                finally:
                    try:
                        device.stop()
                    except Exception:
                        pass

        except SystemExit as exc:
            log.critical("Voice command listener SystemExit — suppressing: %r", exc, exc_info=True)
        except Exception as exc:
            log.error("Voice command listener error: %s", exc)

        log.debug("Voice command listener stopped")

    def stop(self):
        self._running = False
