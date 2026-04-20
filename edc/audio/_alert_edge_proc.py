"""
Alert TTS subprocess — edge-tts variant.
Synthesises speech with Microsoft Edge neural TTS and plays clean audio.
No SAPI5 fallback: pyttsx3 registers as a Windows Communications stream which
triggers audio ducking on other apps.

Usage: python _alert_edge_proc.py <rate_pct> <volume> <voice_name> <sapi_voice_id|__none__> <text>
  rate_pct:      edge-tts rate string e.g. "+0%" or "+10%"
  volume:        float 0.0-1.0
  voice_name:    edge-tts voice e.g. "en-US-AriaNeural"
  sapi_voice_id: unused (kept for call-site compatibility)
  text:          speech text
"""
import asyncio
import io
import sys
import wave


async def _synthesise(voice: str, rate_pct: str, text: str) -> bytes:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate_pct)
    chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def _mp3_to_wav_bytes(mp3_bytes: bytes) -> tuple[bytes, int]:
    """Return (wav_bytes, sample_rate)."""
    import miniaudio
    decoded = miniaudio.decode(mp3_bytes, output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=22050)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(decoded.sample_rate)
        wf.writeframes(decoded.samples.tobytes())
    return buf.getvalue(), decoded.sample_rate


def _configure_audio_session():
    """Restore Windows audio session volume and opt out of comms ducking."""
    import os, time
    pid = os.getpid()
    for _ in range(5):
        try:
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioSessionControl2
            for session in AudioUtilities.GetAllSessions():
                try:
                    ctrl2 = session._ctl.QueryInterface(IAudioSessionControl2)
                    if ctrl2.GetProcessId() != pid:
                        continue
                    ctrl2.SetDuckingPreference(True)
                    vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                    vol.SetMute(False, None)
                    vol.SetMasterVolume(1.0, None)
                    return
                except Exception:
                    continue
        except Exception:
            pass
        time.sleep(0.05)


def _play_wav(wav_bytes: bytes, sample_rate: int, volume: float):
    import numpy as np
    from scipy.io import wavfile
    import sounddevice as sd

    buf = io.BytesIO(wav_bytes)
    sr, data = wavfile.read(buf)

    if data.dtype == "int16":
        data = data.astype("float32") / 32768.0
    elif data.dtype == "int32":
        data = data.astype("float32") / 2147483648.0
    else:
        data = data.astype("float32")
    if data.ndim > 1:
        data = data[:, 0]

    data = data * float(volume)
    sd.play(data, sr)
    _configure_audio_session()
    sd.wait()


def _run(rate_pct: str, volume: float, voice: str, sapi_voice_id: str | None, text: str):
    # sapi_voice_id intentionally unused — SAPI5 triggers Windows audio ducking.
    try:
        mp3_bytes = asyncio.run(_synthesise(voice, rate_pct, text))
        if mp3_bytes:
            wav_bytes, sr = _mp3_to_wav_bytes(mp3_bytes)
            _play_wav(wav_bytes, sr, volume)
    except Exception:
        pass  # Silent skip — a missed line is better than ducking all other audio.


if __name__ == "__main__":
    if len(sys.argv) < 6:
        sys.exit(1)
    _rate_pct     = sys.argv[1]
    _volume       = float(sys.argv[2])
    _voice        = sys.argv[3]
    _sapi_id      = sys.argv[4] if sys.argv[4] != "__none__" else None
    _text         = sys.argv[5]
    _run(_rate_pct, _volume, _voice, _sapi_id, _text)
