"""Squadron Boost limits for the BGS Tasks tracker -- stored in
settings.json like every other setting, defaults from the squadron guide."""
import json
from types import SimpleNamespace

from edc.config import AppConfig, ConfigStore
from edc.ui.main_window import MainWindow


def test_defaults():
    cfg = AppConfig()
    assert cfg.bgs_limit_tier_score == 25
    assert cfg.bgs_limit_bounties_cr == 20_000_000
    assert cfg.bgs_limit_exploration_cr == 20_000_000


def test_round_trip(tmp_path):
    store = ConfigStore(tmp_path)
    cfg = AppConfig()
    cfg.bgs_limit_tier_score = 30
    cfg.bgs_limit_bounties_cr = 15_000_000
    cfg.bgs_limit_exploration_cr = 25_000_000
    store.save(cfg)
    loaded = store.load()
    assert loaded.bgs_limit_tier_score == 30
    assert loaded.bgs_limit_bounties_cr == 15_000_000
    assert loaded.bgs_limit_exploration_cr == 25_000_000


def test_missing_keys_in_an_older_settings_file_use_defaults(tmp_path):
    store = ConfigStore(tmp_path)
    store.ensure_dirs()
    store.path.write_text(json.dumps({"schema_version": 2, "journal_dir": None}), encoding="utf-8")
    loaded = store.load()
    assert loaded.bgs_limit_tier_score == 25
    assert loaded.bgs_limit_bounties_cr == 20_000_000


def _fake_self():
    saved = []
    return SimpleNamespace(cfg=AppConfig(), cfg_store=SimpleNamespace(save=saved.append), _saved=saved)


def test_settings_handlers_store_values_and_save():
    fake_self = _fake_self()
    MainWindow._on_bgs_limit_tier_changed(fake_self, 40)
    MainWindow._on_bgs_limit_bounties_changed(fake_self, 12)
    MainWindow._on_bgs_limit_exploration_changed(fake_self, 30)
    assert fake_self.cfg.bgs_limit_tier_score == 40
    assert fake_self.cfg.bgs_limit_bounties_cr == 12_000_000
    assert fake_self.cfg.bgs_limit_exploration_cr == 30_000_000
    assert len(fake_self._saved) == 3
