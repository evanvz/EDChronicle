"""FSSSignalDiscovered voice callouts (notable stellar phenomena, megaship
PP hints, NHSS) were unreachable for every user -- _tts_router gates on
cfg.tts_events.get(event_type, False), and "FSSSignalDiscovered" was never
in the default dict (no UI exposes these per-event toggles; the dict is
the only control point). Confirmed live: a "Notable stellar phenomena"
signal showed in the Overview panel (state population is unconditional)
but never got a voice callout."""
from edc.config import AppConfig


def test_fss_signal_discovered_tts_enabled_by_default():
    cfg = AppConfig()
    assert cfg.tts_events.get("FSSSignalDiscovered") is True
