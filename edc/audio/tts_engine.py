"""
TTS Engine for EDHelper.
Main alerts use edge-tts (Microsoft Edge neural voices) via subprocess per utterance.
Comms channel uses edge-tts with radio DSP effect.

IMPORTANT: pyttsx3 / SAPI5 is intentionally NOT used for audio playback anywhere in
this engine. Windows classifies SAPI5 ISpVoice COM objects as "Communications" audio
sessions, which triggers Windows' automatic audio ducking (reducing other app audio,
etc. to ~20% volume). Even calling pyttsx3.init() in the main process registers the
Python process as a Communications app for the entire session.
"""

import logging
import queue
import random
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, QObject, pyqtSlot

log = logging.getLogger(__name__)


_ALERT_VOICE_POOL = [
    "en-US-AriaNeural",
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-US-ChristopherNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
    "en-AU-NatashaNeural",
    "en-AU-WilliamNeural",
    "en-CA-ClaraNeural",
    "en-IE-EmilyNeural",
]

_ALERT_VOICE_DISPLAY = [
    "Aria — US Female",
    "Jenny — US Female",
    "Guy — US Male",
    "Christopher — US Male",
    "Sonia — GB Female",
    "Ryan — GB Male",
    "Natasha — AU Female",
    "William — AU Male",
    "Clara — CA Female",
    "Emily — IE Female",
]

_ALERT_PROC = Path(__file__).parent / "_alert_edge_proc.py"


class TTSWorker(QObject):
    """
    Runs inside a QThread.
    Speaks each queued phrase via edge-tts in an isolated subprocess.
    SAPI5 voice ID is passed as fallback for offline use.
    """

    def __init__(self, q: queue.PriorityQueue, rate: int, volume: float,
                 voice_index: int, voice_name: str):
        super().__init__()
        self._queue       = q
        self._rate        = rate
        self._volume      = volume
        self._voice_index = voice_index
        self._voice_name  = voice_name
        self._running     = True

    def _speak_edge(self, text: str, voice: str | None = None):
        rate_pct = f"+{max(0, self._rate - 175)}%" if self._rate >= 175 else f"-{175 - self._rate}%"
        voice = voice or self._voice_name
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [sys.executable, str(_ALERT_PROC), rate_pct, str(self._volume), voice, "__none__", text],
            timeout=30, creationflags=flags,
        )

    def _speak_one(self, text: str, voice: str | None = None):
        self._speak_edge(text, voice)

    @pyqtSlot()
    def run(self):
        log.info(
            f"TTS worker started — rate={self._rate} "
            f"volume={self._volume} voice={self._voice_name}"
        )
        while self._running:
            try:
                _, _counter, text = self._queue.get(timeout=0.5)
                if text is None:
                    break
                try:
                    self._speak_one(text)
                    log.debug(f"TTS spoke: {text[:60]}")
                except subprocess.TimeoutExpired:
                    log.warning("TTS subprocess timed out")
                except Exception as e:
                    log.error(f"TTS speak error: {e}")
            except queue.Empty:
                continue
            except Exception as e:
                log.debug(f"TTS worker loop error: {e}")

        log.debug("TTS worker stopped")

    def stop(self):
        self._running = False


class CommsWorker(QObject):
    """
    Comms channel TTS worker. Queue items are (priority, counter, text, voice_id)
    so each utterance can use a different voice for variety.
    """

    def __init__(self, q: queue.PriorityQueue, rate: int, volume: float):
        super().__init__()
        self._queue   = q
        self._rate    = rate
        self._volume  = volume
        self._running = True

    _PROC      = Path(__file__).parent / "_comms_edge_proc.py"
    _PROC_SAPI = Path(__file__).parent / "_comms_proc.py"

    def _speak_one(self, text: str, voice_id: str | None):
        pan = random.uniform(-0.7, 0.7)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # voice_id is an edge-tts voice name when using the edge proc
        proc = str(self._PROC)
        rate_arg = "+0%"
        subprocess.run(
            [
                sys.executable, proc,
                rate_arg,
                str(self._volume),
                voice_id or "en-US-GuyNeural",
                str(round(pan, 4)),
                text,
            ],
            timeout=30,
            creationflags=flags,
        )

    @pyqtSlot()
    def run(self):
        log.info(f"TTS comms worker started — rate={self._rate} volume={self._volume}")
        while self._running:
            try:
                _, _counter, text, voice_id = self._queue.get(timeout=0.5)
                if text is None:
                    break
                try:
                    self._speak_one(text, voice_id)
                except subprocess.TimeoutExpired:
                    log.warning("TTS comms subprocess timed out")
                except Exception as e:
                    log.error(f"TTS comms speak error: {e}")
            except queue.Empty:
                continue
            except Exception as e:
                log.debug(f"TTS comms worker loop error: {e}")
        log.debug("TTS comms worker stopped")

    def stop(self):
        self._running = False


class TTSEngine:
    """
    Public API for TTS. Creates a QThread + TTSWorker.
    Call speak(text, priority) from any thread.
    priority: 1=critical, 5=normal, 9=background
    """

    def __init__(self, rate: int = 175, volume: float = 0.9, voice_index: int = 0,
                 comms_rate: int = 210, comms_volume: float = 0.35, comms_voice_index: int = 1):
        self._enabled = False
        self._rate    = rate
        self._volume        = volume
        self._voice_index   = voice_index
        self._queue         = queue.PriorityQueue()
        self._counter       = 0
        self._worker        = None
        self._thread        = None
        self._comms_enabled      = False
        self._comms_rate         = comms_rate
        self._comms_volume       = comms_volume
        self._comms_voice_index  = comms_voice_index
        self._comms_queue        = queue.PriorityQueue()
        self._comms_counter      = 0
        self._comms_worker       = None
        self._comms_thread       = None
        self._comms_voice_pool: list[str] = []

    def start(self):
        """Start the TTS worker thread."""
        if self._thread and self._thread.isRunning():
            return
        voice_name = _ALERT_VOICE_POOL[self._voice_index] if self._voice_index < len(_ALERT_VOICE_POOL) else _ALERT_VOICE_POOL[0]
        self._worker = TTSWorker(
            self._queue, self._rate, self._volume,
            self._voice_index, voice_name
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._thread.start()
        log.info(f"TTS engine thread started — voice={voice_name}")

        self._comms_voice_pool = [
            "en-US-GuyNeural",
            "en-US-ChristopherNeural",
            "en-GB-RyanNeural",
            "en-AU-WilliamNeural",
            "en-CA-LiamNeural",
            "en-IE-ConnorNeural",
            "en-IN-PrabhatNeural",
            "en-US-EricNeural",
            "en-US-RogerNeural",
            "en-GB-ThomasNeural",
        ]
        log.info(f"TTS comms voice pool: {len(self._comms_voice_pool)} edge-tts voices")

        self._comms_worker = CommsWorker(
            self._comms_queue, self._comms_rate, self._comms_volume
        )
        self._comms_thread = QThread()
        self._comms_worker.moveToThread(self._comms_thread)
        self._comms_thread.started.connect(self._comms_worker.run)
        self._comms_thread.start()
        log.info("TTS comms thread started")

    def stop(self):
        """Stop the worker thread cleanly."""
        if self._worker:
            self._worker.stop()
        try:
            self._queue.put_nowait((0, 0, None))
        except Exception:
            pass
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)

        if self._comms_worker:
            self._comms_worker.stop()
        try:
            self._comms_queue.put_nowait((0, 0, None, None))
        except Exception:
            pass
        if self._comms_thread:
            self._comms_thread.quit()
            self._comms_thread.wait(3000)

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)

    def speak(self, text: str, priority: int = 5):
        """Queue a phrase. Lower priority number = spoken sooner."""
        if not self._enabled:
            return
        if not isinstance(text, str) or not text.strip():
            return
        self._counter += 1
        try:
            self._queue.put_nowait((priority, self._counter, text))
        except Exception:
            pass

    def speak_comms(self, text: str):
        """Queue a comms phrase using a randomly picked voice from the pool."""
        if not self._comms_enabled:
            return
        if not isinstance(text, str) or not text.strip():
            return
        if self._comms_queue.qsize() >= 3:
            return
        pool = getattr(self, "_comms_voice_pool", [])
        voice_id = random.choice(pool) if pool else None
        self._comms_counter += 1
        try:
            self._comms_queue.put_nowait((5, self._comms_counter, text, voice_id))
        except Exception:
            pass

    def load_from_config(self, cfg):
        """Apply settings from AppConfig."""
        try:
            self._enabled = bool(getattr(cfg, "tts_enabled", False))
            self._rate    = int(getattr(cfg, "tts_rate", 175) or 175)
            self._volume        = float(getattr(cfg, "tts_volume", 0.9) or 0.9)
            self._voice_index   = int(getattr(cfg, "tts_voice_index", 0) or 0)
            self._comms_enabled = bool(getattr(cfg, "comms_enabled", False))
            self._comms_rate        = int(getattr(cfg, "comms_rate", 210) or 210)
            self._comms_volume      = float(getattr(cfg, "comms_volume", 0.35) or 0.35)
            self._comms_voice_index = int(getattr(cfg, "comms_voice_index", 1) or 1)
            if self._worker:
                self._worker._rate       = self._rate
                self._worker._volume     = self._volume
                self._worker._voice_name = (
                    _ALERT_VOICE_POOL[self._voice_index]
                    if self._voice_index < len(_ALERT_VOICE_POOL)
                    else _ALERT_VOICE_POOL[0]
                )
            if self._comms_worker:
                self._comms_worker._rate   = self._comms_rate
                self._comms_worker._volume = self._comms_volume
        except Exception:
            pass

    def speak_test(self, text: str, voice_index: int):
        """Speak a test phrase using the exact selected voice. Runs in a daemon thread."""
        import threading
        voice_name = _ALERT_VOICE_POOL[voice_index] if voice_index < len(_ALERT_VOICE_POOL) else _ALERT_VOICE_POOL[0]
        worker = TTSWorker(queue.PriorityQueue(), self._rate, self._volume, voice_index, voice_name)
        threading.Thread(target=lambda: worker._speak_edge(text, voice_name), daemon=True).start()

    def get_available_voices(self) -> list:
        """Returns list of (index, display_name) for settings dialog — edge-tts voices."""
        return list(enumerate(_ALERT_VOICE_DISPLAY))

