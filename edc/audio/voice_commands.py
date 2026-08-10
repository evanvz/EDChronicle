"""
Voice command listener — offline speech recognition via Vosk.

Two command domains, both matched the same way — trigger word and phrase
spoken together in one utterance:

  App navigation  — "hud [tab]" switches the active panel, e.g. "hud overview"
  Ship commands   — "[trigger] [phrase]" fires an in-game action, e.g. "ship boost"

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
    "exploration":  "Exploration",
    "exobiology":   "Exobiology",
    "biology":      "Exobiology",
    "powerplay":    "PowerPlay",
    "combat":       "Combat",
    "intel":        "Intel",
    "engineering":  "Engineering",
    "carrier":      "Fleet Carrier",
    "market":       "Market",
    "materials":    "Materials",
    "mining":       "Mining",
    "odyssey":      "Odyssey",
    "faction":      "Player Faction",
    "squadron":     "Squadron",
}

# Default nav trigger word, said together with a tab name in one utterance
# e.g. "hud overview", "hud exploration" — same pattern as ship commands.
# User-configurable via set_nav_trigger_word(); see VoiceCommandListener.
_DEFAULT_NAV_TRIGGER_WORD = "hud"

# ── Vosk model ────────────────────────────────────────────────────────────────

MODEL_URL      = "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip"
MODEL_DIR_NAME = "vosk"

_POST_ACTION_BLACKOUT = 0.4  # command matching needs the trigger word, so TTS
                             # confirm echo can't fire commands — keep this short
_FRAGMENT_WINDOW      = 5.0   # seconds — join final results this close together before matching.
                              # Generous on purpose: Vosk finalisation adds ~1-1.5s after speech
                              # ends, so phrase text often lands 2-2.6s after the trigger's
                              # timestamp — a tight window silently dropped slow-paced commands.
                              # Stale-state concerns are handled by the trigger word instantly
                              # resetting the buffer, not by keeping this short.

_LOOPBACK_HINTS = ("stereo mix", "what u hear", "loopback", "wave out", "speakers")


def _pick_capture_device(miniaudio_mod, preferred_name: str | None = None):
    """
    Pick a real microphone input, avoiding loopback/"Stereo Mix" style devices
    that capture system audio playback instead of the mic.
    If preferred_name is given (from the user's Voice Cmds panel selection), it
    is matched first. Returns (device_id, name) or (None, None) for OS default.
    """
    try:
        devices = miniaudio_mod.Devices()
        captures = devices.get_captures()
    except Exception as exc:
        log.warning("Could not enumerate capture devices: %s", exc)
        return None, None

    log.info("Available capture devices: %s", [d["name"] for d in captures])

    if preferred_name:
        for d in captures:
            if d["name"] == preferred_name:
                log.info("Using user-selected microphone: %s", d["name"])
                return d["id"], d["name"]
        log.warning("Selected microphone '%s' not found — falling back to auto-detect", preferred_name)

    non_loopback = [d for d in captures if not any(h in d["name"].lower() for h in _LOOPBACK_HINTS)]

    for keyword in ("headset", "microphone", "mic"):
        for d in non_loopback:
            if keyword in d["name"].lower():
                log.info("Using capture device: %s", d["name"])
                return d["id"], d["name"]

    if non_loopback:
        log.info("Using capture device: %s", non_loopback[0]["name"])
        return non_loopback[0]["id"], non_loopback[0]["name"]

    if captures:
        log.warning("Only loopback-style capture devices found — using '%s' "
                    "(may pick up system audio)", captures[0]["name"])
        return captures[0]["id"], captures[0]["name"]

    log.warning("No capture devices found — using OS default")
    return None, None


def ensure_model(models_dir: Path) -> Path | None:
    model_path = models_dir / MODEL_DIR_NAME
    if model_path.exists():
        return model_path
    log.info("vosk model not found — downloading (~128 MB)...")
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


_vocab_model = None  # lazily-loaded vosk.Model, cached — loading takes ~1-2s


def missing_vocab_words(words: list[str], models_dir: Path) -> list[str]:
    """
    Return the subset of `words` that Vosk's acoustic model doesn't recognise
    at all (e.g. 'hardpoints', 'supercruise'). Used to warn the user before
    they configure a phrase that can never be recognised, regardless of
    grammar/threshold tuning. Returns [] if the model can't be loaded.
    """
    global _vocab_model
    if _vocab_model is None:
        model_path = models_dir / MODEL_DIR_NAME
        if not model_path.exists():
            return []
        try:
            from vosk import Model
            _vocab_model = Model(str(model_path))
        except Exception as exc:
            log.warning("Could not load vosk model for vocabulary check: %s", exc)
            return []
    missing = []
    for w in words:
        w = w.lower().strip()
        if w and _vocab_model.vosk_model_find_word(w) == -1:
            missing.append(w)
    return missing


class VoiceCommandListener(QObject):
    """
    Listens for voice commands and emits signals for both domains.

    App navigation:  say "hud [tab]"  e.g. "hud overview"
    Ship commands:   say "[trigger_word] [phrase]"  e.g. "ship boost"

    Call update_ship_commands() / set_nav_trigger_word() whenever settings
    change — the grammar is rebuilt on the next audio cycle.
    """

    command_detected      = pyqtSignal(str)   # tab name for app navigation
    ship_command_detected = pyqtSignal(str)   # phrase for ship commands
    listener_ready        = pyqtSignal()      # mic capture started — fires once per listener session
    trigger_heard         = pyqtSignal()      # bare trigger word heard — "now listening for command" cue
    command_unrecognised  = pyqtSignal()      # trigger heard but phrase matched nothing — retry cue

    SAMPLE_RATE = 16000
    BLOCK_SIZE  = 4000   # 0.25s — smaller chunks so partials and finals surface sooner

    def __init__(self, models_dir: Path):
        super().__init__()
        self._models_dir         = models_dir
        self._running            = False
        self._trigger_word       = "ship"
        self._nav_trigger_word   = _DEFAULT_NAV_TRIGGER_WORD
        self._ship_commands: list[dict] = []
        self._grammar_json       = self._build_grammar()
        self._input_device_name: str | None = None

    # ── Public config API ─────────────────────────────────────────────────────

    def update_ship_commands(self, commands: list[dict], trigger_word: str = "ship"):
        """Called from main thread whenever voice_commands.json changes."""
        self._ship_commands = commands
        self._trigger_word  = trigger_word.lower().strip() or "ship"
        self._grammar_json  = self._build_grammar()
        log.info("Ship commands updated: %d active, trigger='%s'",
                 len(commands), self._trigger_word)

    def set_nav_trigger_word(self, word: str | None):
        """Called from main thread whenever the nav trigger word setting changes."""
        new_word = (word or "").lower().strip() or _DEFAULT_NAV_TRIGGER_WORD
        if new_word != self._nav_trigger_word:
            self._nav_trigger_word = new_word
            self._grammar_json = self._build_grammar()

    def set_input_device(self, device_name: str | None):
        """Called from main thread when the user picks a microphone in the panel."""
        self._input_device_name = device_name

    # ── Grammar ───────────────────────────────────────────────────────────────

    def _build_grammar(self) -> str:
        """
        Build Vosk's grammar as full phrases (trigger + command together), not
        just a word-vocabulary list. This constrains the decoder to score each
        whole phrase against the audio, which is far less prone to cross-phrase
        word confusion than free word-by-word transcription within a vocabulary.
        """
        phrases: set[str] = set()
        # Bare trigger words too — so a pause right after the trigger still
        # transcribes literally instead of being swallowed as [unk], which
        # would otherwise break fragment-joining recovery across the pause.
        phrases.add(self._nav_trigger_word)
        phrases.add(self._trigger_word)
        # Nav: "<nav_trigger> <tab>" for every tab keyword
        for tab_word in TAB_PHRASES:
            phrases.add(f"{self._nav_trigger_word} {tab_word}")
        # Ship: "<trigger> <phrase>" for every active command
        for cmd in self._ship_commands:
            phrase = cmd.get("phrase", "").lower().strip()
            if phrase:
                phrases.add(f"{self._trigger_word} {phrase}")
        vocab = sorted(phrases) + ["[unk]"]
        return json.dumps(vocab)

    # ── Matching ──────────────────────────────────────────────────────────────

    def _clean(self, text: str) -> list[str]:
        return [w for w in text.lower().split() if w != "[unk]"]

    def _match_nav(self, words: list[str]) -> str | None:
        if self._nav_trigger_word not in words:
            return None
        for word in words:
            if word in TAB_PHRASES:
                return TAB_PHRASES[word]
        return None

    def _match_ship(self, words: list[str]) -> dict | None:
        """Match trigger word + phrase spoken together in one utterance, e.g. 'ship boost'."""
        if self._trigger_word not in words:
            return None
        idx  = words.index(self._trigger_word)
        tail = words[idx + 1:]
        if not tail:
            return None
        tail_str = " ".join(tail)
        # Exact match first
        for cmd in self._ship_commands:
            if cmd.get("phrase", "").lower() == tail_str:
                return cmd
        # Partial: every phrase word present in the tail
        tail_set = set(tail)
        for cmd in self._ship_commands:
            phrase_words = set(cmd.get("phrase", "").lower().split())
            if phrase_words and phrase_words.issubset(tail_set):
                return cmd
        # Near-miss: Vosk regularly drops one word inside phrases — either a
        # word of a longer phrase ("open system scanner" → "system scanner")
        # or a tiny connector ("o seven" → "seven", "speed up" → "speed").
        # Tolerate exactly one missing word when it's a 3+ word phrase, or a
        # 2-word phrase whose missing word is tiny (≤2 chars, acoustically
        # fragile). Only ever fire when that identifies a SINGLE command —
        # "power to engines"/"power to systems" differ by one word and
        # guessing between candidates would misfire.
        candidates = []
        for cmd in self._ship_commands:
            phrase_words = set(cmd.get("phrase", "").lower().split())
            missing = phrase_words - tail_set
            if len(missing) != 1:
                continue
            if len(phrase_words) >= 3 or len(next(iter(missing))) <= 2:
                candidates.append(cmd)
        if len(candidates) == 1:
            log.info("Near-miss match (1 word dropped): tail=%s → '%s'",
                     tail, candidates[0].get("phrase", ""))
            return candidates[0]
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
        fragments: list[tuple[float, list[str]]] = []   # recent (timestamp, words) for split-utterance recovery
        ready_announced = False   # "system ready" cue fires once per listener session
        log.info("Voice command listener active — trigger='%s', %d ship commands",
                 self._trigger_word, len(self._ship_commands))

        try:
            import miniaudio

            audio_q: queue.Queue = queue.Queue()

            while self._running:
                # Rebuild recogniser each loop so grammar picks up any updates.
                # Constraining to our small vocabulary is what keeps background
                # audio (TV/YouTube/game dialogue) from being transcribed at all.
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
                    device_id, device_name = _pick_capture_device(miniaudio, self._input_device_name)
                    device = miniaudio.CaptureDevice(
                        input_format=miniaudio.SampleFormat.SIGNED16,
                        nchannels=1,
                        sample_rate=self.SAMPLE_RATE,
                        buffersize_msec=int(self.BLOCK_SIZE / self.SAMPLE_RATE * 1000),
                        device_id=device_id,
                    )
                    device.start(gen)
                    log.info("Voice capture started on: %s", device_name or "OS default")
                    if not ready_announced:
                        self.listener_ready.emit()
                        ready_announced = True
                except Exception as exc:
                    log.warning("Voice capture device unavailable, retrying in 3s: %s", exc)
                    time.sleep(3)
                    continue

                # Tracks whether the current in-progress utterance already got a
                # trigger beep from a partial result, so the final doesn't re-beep.
                partial_trigger_beeped = False
                # Background audio (music/game/TV bleeding into the mic) can get
                # misheard as the trigger word — the grammar is deliberately a
                # tiny vocabulary, so any sound gets forced into the closest
                # match. Requiring the SAME trigger word to show up in two
                # consecutive partial updates (not just one) filters out a
                # single-chunk misfire while still firing well before Vosk
                # would finalize the utterance.
                consecutive_trigger_partials = 0

                try:
                    while self._running:
                        try:
                            data = audio_q.get(timeout=0.5)
                        except queue.Empty:
                            continue

                        now = time.monotonic()

                        if not rec.AcceptWaveform(data):
                            # Partial results are used ONLY to acknowledge the bare
                            # trigger word early — command matching stays on final
                            # results, which proved far more stable. This makes the
                            # "I'm listening" cue near-instant instead of waiting
                            # ~1-2s for Vosk to detect end-of-utterance silence.
                            if partial_trigger_beeped or now < blackout_until:
                                continue
                            presult = json.loads(rec.PartialResult())
                            pwords  = self._clean(presult.get("partial", ""))
                            if pwords in ([self._trigger_word], [self._nav_trigger_word]):
                                consecutive_trigger_partials += 1
                                if consecutive_trigger_partials >= 2:
                                    partial_trigger_beeped = True
                                    # Saying the trigger starts a fresh attempt — drop any
                                    # stale unmatched words so a retry isn't polluted.
                                    fragments = [(now, pwords)]
                                    log.info("Trigger heard (partial): %s", pwords)
                                    self.trigger_heard.emit()
                            else:
                                consecutive_trigger_partials = 0
                            continue

                        result = json.loads(rec.Result())
                        words  = self._clean(result.get("text", ""))
                        already_beeped = partial_trigger_beeped
                        partial_trigger_beeped = False
                        consecutive_trigger_partials = 0
                        if not words:
                            continue
                        log.info("Voice final: %s", words)

                        if now < blackout_until:
                            continue

                        # Drop fragments older than the window, then add this one.
                        # A pause between "ship" and "boost" often finalizes as two
                        # separate results — joining recent ones recovers the phrase.
                        fragments = [(t, w) for t, w in fragments if now - t <= _FRAGMENT_WINDOW]
                        fragments.append((now, words))
                        combined = [w for _, ws in fragments for w in ws]

                        ship_cmd = self._match_ship(combined)
                        if ship_cmd:
                            phrase = ship_cmd.get("phrase", "")
                            log.info("Ship command: %s → '%s'", combined, phrase)
                            self.ship_command_detected.emit(phrase)
                            blackout_until = now + _POST_ACTION_BLACKOUT
                            fragments = []
                            continue

                        # Nav matching is skipped when the ship trigger is present —
                        # the user clearly started a ship command, and letting nav
                        # fire off stale or misheard words was switching app tabs
                        # mid ship-phrase.
                        if self._trigger_word not in combined:
                            tab = self._match_nav(combined)
                            if tab:
                                log.info("Nav command: %s → %s", combined, tab)
                                self.command_detected.emit(tab)
                                blackout_until = now + _POST_ACTION_BLACKOUT
                                fragments = []
                                continue

                        # Bare trigger word alone — acknowledge it was heard (unless
                        # a partial already did) and reset to a fresh attempt.
                        if words in ([self._trigger_word], [self._nav_trigger_word]):
                            fragments = [(now, words)]
                            if not already_beeped:
                                log.info("Trigger heard: %s", words)
                                self.trigger_heard.emit()
                            continue

                        # A trigger was heard but nothing matched (usually a
                        # mishear) — tell the user so they can retry immediately
                        # instead of assuming a hang. A single-word final stays
                        # silent ONLY if that word appears in some enabled phrase
                        # (it may be a mid-phrase pause with the rest still
                        # coming); a word belonging to no phrase can never
                        # complete into a match, so it tones right away.
                        if (self._trigger_word in combined
                                or self._nav_trigger_word in combined):
                            if len(words) == 1:
                                known = {w for c in self._ship_commands
                                         for w in c.get("phrase", "").lower().split()}
                                known.update(TAB_PHRASES.keys())
                                if words[0] in known:
                                    continue  # possibly mid-phrase — wait for more
                            log.info("Unrecognised phrase: %s", combined)
                            self.command_unrecognised.emit()

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
