"""Untrusted text (EDDN names, feed titles) is escaped before going into
rich-text labels, only https links are made clickable, and the voice model
download is rejected on a checksum mismatch."""
from types import SimpleNamespace
from unittest.mock import patch

from edc.ui.main_window import MainWindow


def test_galnet_title_escaped_and_non_https_link_dropped():
    shown = []
    fake = SimpleNamespace(_galnet_label=SimpleNamespace(setText=shown.append, setToolTip=lambda t: None),
                           _galnet_headline_index=0,
                           _galnet_headlines=[("<b>Fake</b> news", "file:///C:/Windows/notepad.exe"),
                                              ("Real news", "https://community.elitedangerous.com/en/galnet/uid/x")])
    MainWindow._show_galnet_headline(fake)
    assert shown[-1] == "📰 &lt;b&gt;Fake&lt;/b&gt; news"          # no link, tags shown as text
    fake._galnet_headline_index = 1
    MainWindow._show_galnet_headline(fake)
    assert '<a href="https://community.elitedangerous.com/en/galnet/uid/x"' in shown[-1]


def test_vosk_download_with_wrong_checksum_is_not_installed(tmp_path):
    from edc.audio import voice_commands as vc

    def fake_download(url, path):
        open(path, "wb").write(b"not the real model")

    with patch.object(vc.urllib.request, "urlretrieve", fake_download):
        assert vc.ensure_model(tmp_path) is None
    assert not (tmp_path / "_vosk_model.zip").exists()
    assert not (tmp_path / vc.MODEL_DIR_NAME).exists()


def test_session_report_escapes_faction_names():
    """A faction name from EDDN can be anything; markup in it must show as text."""
    from PyQt6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from edc.ui.panels.session_activity_dialog import SessionActivityDialog
    entry = {"missions": {"count": 1, "weighted": 1, "primary_count": 1, "secondary_count": 0,
                          "by_type": {}, "reward_total": 0, "reward_by_type": {}},
             "combat_bonds_total": 0, "bounties_total": 0, "bounties_max_cashin": 0,
             "cz_kills": {}, "trade_sold": {}}
    dlg = SessionActivityDialog(SimpleNamespace())
    dlg._render_report({"2026-10-08": {"Ekono": {'<a href="x">Click me</a>': entry}}})
    texts = [w.text() for c in dlg._cards for w in c.findChildren(QLabel)]
    assert any("&lt;a href=&quot;x&quot;&gt;Click me&lt;/a&gt;" in t for t in texts)
    assert not any('<a href="x">' in t for t in texts)
