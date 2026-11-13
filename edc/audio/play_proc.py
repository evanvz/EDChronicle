# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""
Plays one sound in its own short-lived process.

Windows audio calls can freeze for good when the output device changes (laptop
speakers <-> Bluetooth earphones, 2026-11-12: both voice threads stuck inside
MMDevApi.dll, and the frozen app then blocked the earphones for the whole PC).
A frozen thread cannot be stopped, a frozen process can: play() ends a helper
that overruns its phrase and plays the phrase again on a fresh one.

play() is the app side. main() is the helper: `python -m edc.audio.play_proc`.
"""
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_WIDTH = {"SIGNED16": 2, "FLOAT32": 4}   # bytes per sample
_STALL_SECONDS = 5                       # allowed on top of the sound's own length
_SPARES = 2                              # alert and comms voice can speak at once
_spare: list = []
_lock = threading.Lock()


def _spawn():
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "edc.audio.play_proc"], cwd=_ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW)


def warm():
    """Starts the waiting helpers, so a phrase does not pay for a Python start."""
    with _lock:
        _spare[:] = [p for p in _spare if p.poll() is None]
        while len(_spare) < _SPARES:
            _spare.append(_spawn())


def _take():
    with _lock:
        live = [p for p in _spare if p.poll() is None]
        proc = live.pop(0) if live else _spawn()
        _spare[:] = live
    warm()
    return proc


def _feed(proc, data: bytes):
    try:
        proc.stdin.write(data)
        proc.stdin.close()
    except OSError:
        pass  # helper ended first; play() reads its exit code


def play(pcm: bytes, fmt: str, channels: int, sample_rate: int, device_name: str | None = None,
         interrupt: threading.Event | None = None, unduck: bool = False, buffer_ms: int = 100) -> bool:
    """Plays raw PCM and returns when it has finished. fmt is "SIGNED16" or "FLOAT32".
    Setting `interrupt` cuts the sound off. Returns False if it could not be played."""
    head = json.dumps({"fmt": fmt, "channels": channels, "sample_rate": sample_rate,
                       "device": device_name, "unduck": unduck, "buffer_ms": buffer_ms}).encode() + b"\n"
    limit = len(pcm) / (sample_rate * channels * _WIDTH[fmt]) + _STALL_SECONDS
    for attempt in (1, 2):
        proc = _take()
        # On a thread: a helper that never reads would block this write for good.
        threading.Thread(target=_feed, args=(proc, head + pcm), daemon=True).start()
        deadline = time.monotonic() + limit
        while proc.poll() is None and time.monotonic() < deadline:
            if interrupt is not None and interrupt.is_set():
                proc.kill()
                return True
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
            log.warning("Voice playback stalled for %.0fs, helper ended%s", limit,
                        "; playing the phrase again" if attempt == 1 else "; phrase dropped")
            continue
        said = proc.stderr.read().decode("utf-8", errors="replace").strip()
        if proc.returncode:
            log.error("Voice playback failed: %s", said.splitlines()[-1] if said else proc.returncode)
            return False
        if said:
            log.warning("%s", said)
        return True
    return False


def main():
    import os
    import miniaudio
    from edc.audio.audio_devices import resolve_playback_device_id

    line = sys.stdin.buffer.readline()   # a spare waits here until it gets a sound
    if not line:
        return                           # app closed without using this spare
    head = json.loads(line)
    pcm = sys.stdin.buffer.read()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    step = head["channels"] * _WIDTH[head["fmt"]]
    done = threading.Event()

    def _gen():
        pos = 0
        try:
            num_frames = yield b""
            while pos < len(pcm):
                chunk = pcm[pos:pos + num_frames * step]
                pos += num_frames * step
                num_frames = yield chunk
        finally:
            done.set()

    device = miniaudio.PlaybackDevice(
        output_format=getattr(miniaudio.SampleFormat, head["fmt"]),
        nchannels=head["channels"],
        sample_rate=head["sample_rate"],
        buffersize_msec=head["buffer_ms"],
        device_id=resolve_playback_device_id(head["device"]),
    )
    gen = _gen()
    next(gen)
    device.start(gen)
    if head["unduck"]:
        from edc.audio._comms_edge_proc import _configure_audio_session
        _configure_audio_session()
    done.wait()
    time.sleep(head["buffer_ms"] / 1000 + 0.1)   # let the last buffer play out
    sys.stderr.flush()
    # No device.stop()/close(): those are the calls that froze. Exiting frees the device.
    os._exit(0)


if __name__ == "__main__":
    main()
