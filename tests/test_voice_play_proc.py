"""A voice helper that never finishes is ended and the phrase is played again (2026-11-12 freeze)."""
import subprocess
import sys

from edc.audio import play_proc


def test_a_stalled_helper_is_ended_and_the_phrase_replayed_once(monkeypatch):
    spawned = []

    def stuck_helper():
        spawned.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                        stdin=subprocess.PIPE, stderr=subprocess.PIPE))
        return spawned[-1]

    monkeypatch.setattr(play_proc, "_spawn", stuck_helper)
    monkeypatch.setattr(play_proc, "_spare", [])
    monkeypatch.setattr(play_proc, "_SPARES", 0)
    monkeypatch.setattr(play_proc, "_STALL_SECONDS", 0.3)

    assert play_proc.play(bytes(48000), "SIGNED16", 1, 24000) is False   # 1 s of silence, never played
    assert len(spawned) == 2
    assert all(p.wait(5) is not None for p in spawned)
