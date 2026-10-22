"""Voice output can follow the Windows default device (switching to headphones
in Windows moves Commander Assist too), or stay on a named device."""
import json
from unittest import mock

from PyQt6.QtWidgets import QApplication

from edc.audio.audio_devices import resolve_playback_device_id


def test_windows_default_is_the_first_choice_and_saves_as_none(tmp_path):
    QApplication.instance() or QApplication([])
    from edc.ui.panels.voice_commands_panel import VoiceCommandsPanel
    cfg = tmp_path / "vc.json"
    cfg.write_text(json.dumps({"output_device": "Speakers (Realtek(R) Audio)"}), encoding="utf-8")
    panel = VoiceCommandsPanel(cfg)
    assert panel._output_combo.itemText(0).startswith("Windows default")
    panel._output_combo.setCurrentIndex(0)
    assert panel.output_device() is None
    assert json.loads(cfg.read_text(encoding="utf-8"))["output_device"] is None


def test_no_device_name_means_os_default():
    with mock.patch("miniaudio.Devices") as devices:
        assert resolve_playback_device_id(None) is None
        devices.assert_not_called()
