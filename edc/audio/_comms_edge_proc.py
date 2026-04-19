"""
Comms radio subprocess — edge-tts variant.
Synthesises speech with Microsoft Edge neural TTS, applies handheld-radio DSP,
plays with stereo panning. No SAPI5 fallback — SAPI5 triggers Windows audio ducking.

Usage: python _comms_edge_proc.py <rate_pct> <volume> <voice_name> <pan> <text>
  rate_pct:   integer percentage offset e.g. "+10" or "-5" (edge-tts format)
  volume:     float 0.0-1.0 (applied in DSP chain)
  voice_name: edge-tts voice name e.g. "en-US-GuyNeural"
  pan:        float -1.0 to 1.0
  text:       speech text
"""
import asyncio
import io
import os
import sys


def _make_radio_click(sr: int, volume: float) -> "np.ndarray":
    """Synthesise a ~40 ms PTT click transient (mono float32)."""
    import numpy as np
    from scipy.signal import butter, sosfilt

    n = int(sr * 0.040)
    t = np.linspace(0, 1, n, endpoint=False)

    # Noise burst shaped by a fast attack / decay envelope
    env = np.exp(-t * 80.0) * (1.0 - np.exp(-t * 600.0))
    click = np.random.normal(0, 1.0, n).astype("float32") * env.astype("float32")

    # Narrow band — keeps it in the radio telephony range
    sos = butter(4, [600, 2400], btype="band", fs=sr, output="sos")
    click = sosfilt(sos, click).astype("float32")

    # Light saturation so it feels punchy
    click = np.tanh(click * 5.0).astype("float32")

    peak = float(np.max(np.abs(click)))
    if peak > 0:
        click = click / peak * float(volume) * 0.7

    return click.astype("float32")


def _to_stereo(mono: "np.ndarray", pan: float, left_gain: float, right_gain: float) -> "np.ndarray":
    import numpy as np
    return np.column_stack([mono * left_gain, mono * right_gain]).astype("float32")


def _silence(sr: int, ms: int) -> "np.ndarray":
    import numpy as np
    return np.zeros(int(sr * ms / 1000), dtype="float32")


def _dsp_and_play(pcm_bytes: bytes, sample_rate: int, volume: float, pan: float):
    import numpy as np
    from scipy.io import wavfile
    from scipy.signal import butter, sosfilt
    import sounddevice as sd

    buf = io.BytesIO(pcm_bytes)
    sr, data = wavfile.read(buf)

    if data.dtype == "int16":
        data = data.astype("float32") / 32768.0
    elif data.dtype == "int32":
        data = data.astype("float32") / 2147483648.0
    else:
        data = data.astype("float32")
    if data.ndim > 1:
        data = data[:, 0]

    peak = float(np.max(np.abs(data)))
    if peak > 0:
        data = data / peak * 0.85

    sos = butter(5, [400, 2800], btype="band", fs=sr, output="sos")
    data = sosfilt(sos, data)
    data = np.tanh(data * 7.0) / 7.0
    data += np.random.normal(0, 0.004, len(data)).astype("float32")
    data = np.clip(data * float(volume) * 1.8, -1.0, 1.0)

    pan = float(max(-1.0, min(1.0, pan)))
    left_g  = float(np.sqrt(0.5 * (1.0 - pan)))
    right_g = float(np.sqrt(0.5 * (1.0 + pan)))

    click   = _make_radio_click(sr, volume)
    gap     = _silence(sr, 30)

    full = np.concatenate([
        _to_stereo(click, pan, left_g, right_g),
        _to_stereo(gap,   pan, left_g, right_g),
        np.column_stack([data * left_g, data * right_g]).astype("float32"),
        _to_stereo(gap,   pan, left_g, right_g),
        _to_stereo(click, pan, left_g, right_g),
    ])

    sd.play(full, sr)
    sd.wait()


async def _synthesise(voice: str, rate_pct: str, text: str) -> bytes:
    """Return WAV bytes from edge-tts."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate_pct)
    chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def _mp3_to_wav_bytes(mp3_bytes: bytes) -> bytes:
    """Decode MP3 → WAV bytes using miniaudio."""
    import miniaudio
    decoded = miniaudio.decode(mp3_bytes, output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=22050)
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(decoded.sample_rate)
        wf.writeframes(decoded.samples.tobytes())
    return buf.getvalue()


def _run(rate_pct: str, volume: float, voice: str, pan: float, text: str):
    # SAPI5 fallback removed — it registers as a Windows Communications stream
    # and triggers audio ducking on other apps.
    try:
        mp3_bytes = asyncio.run(_synthesise(voice, rate_pct, text))
        if mp3_bytes:
            wav_bytes = _mp3_to_wav_bytes(mp3_bytes)
            _dsp_and_play(wav_bytes, 22050, volume, pan)
    except Exception:
        pass  # Silent skip — a missed comms line is better than ducking all other audio.


if __name__ == "__main__":
    if len(sys.argv) < 6:
        sys.exit(1)
    _rate_pct = sys.argv[1]
    _volume   = float(sys.argv[2])
    _voice    = sys.argv[3]
    _pan      = float(sys.argv[4])
    _text     = sys.argv[5]
    _run(_rate_pct, _volume, _voice, _pan, _text)
