"""Shared helper for resolving a named playback device to a miniaudio device_id."""
import logging

log = logging.getLogger(__name__)


def resolve_playback_device_id(device_name: str | None):
    """Return the miniaudio device_id for the given output device name, or None
    to use the OS default. Looked up fresh each call so device changes take
    effect without restarting playback."""
    if not device_name:
        return None
    try:
        import miniaudio
        for d in miniaudio.Devices().get_playbacks():
            if d["name"] == device_name:
                return d["id"]
        log.warning("Selected output device '%s' not found — using OS default", device_name)
    except Exception as exc:
        log.warning("Could not resolve output device '%s': %s", device_name, exc)
    return None
