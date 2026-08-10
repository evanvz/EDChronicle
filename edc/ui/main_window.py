import json
import logging
import time
from datetime import date
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QMessageBox,
    QSlider,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QSplitter,
    QStackedWidget,
    QGraphicsOpacityEffect,
    QFrame,
    QAbstractScrollArea,
    QSizePolicy,
)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, Qt, QTimer, QSettings, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QTextCursor, QColor, QIcon
from pathlib import Path

from edc.core.state import GameState
from edc.core.event_engine import EventEngine
from edc.core.journal_watcher import JournalWatcher
from edc.ui.watcher_controller import WatcherController
from edc.ui.system_data_loader import SystemDataLoader
from edc.ui.panels.combat_panel import CombatPanel
from edc.ui.panels.inventory_panel import ShiplockerPanel, MaterialsPanel
from edc.ui.panels.powerplay_panel import PowerplayPanel
from edc.ui.panels.overview_panel import OverviewPanel
from edc.ui.panels.exploration_panel import ExplorationPanel
from edc.ui.panels.exobiology_panel import ExobiologyPanel
from edc.ui.panels.intel_panel import IntelPanel
from edc.core.status_watcher import StatusWatcher
from edc.core.planet_values import PlanetValueTable
from edc.core.exo_values import ExoValueTable
from edc.core.external_intel import ExternalIntel
from edc.core.item_catalog import ItemCatalog
from edc.core.farming_locations import FarmingLocations
from edc.core.powerplay_activities import PowerPlayActivityTable
from edc.core.spansh_client import SpanshClient as _SpanshClient
from edc.core.edsm_powerplay import EdsmPowerPlayCache
from edc.core.eddn_publisher import EddnPublisher
from edc.core.canonn_client import CanonnClient, SystemPoi
from edc.core.engineering_blueprints import EngineeringBlueprintTable
from edc.core.experimental_effects import ExperimentalEffectsTable
from edc.core.engineering_wishlist import EngineeringWishlist
from edc.core.odyssey_engineering import OdysseyEngineeringTable
from edc.core.odyssey_wishlist import OdysseyWishlist
from edc.core.market_destination import MarketDestinationStore
from edc.core.megaship_tracker import MegashipTracker
from edc.core.mission_events import MISSION_EVENT_NAMES
from edc.core.megaship_scanner import scan_visited_megaships
from edc.core.faction_refresh_tracker import FactionRefreshTracker
from edc.ui.panels.engineering_panel import EngineeringPanel
from edc.audio.handlers.engineering import EngineeringPhrases
from edc.ui.panels.fleet_carrier_panel import FleetCarrierPanel
from edc.core.eddn_powerplay import EddnPowerPlayCache
from edc.core.eddn_listener import EddnPowerPlayWorker
from edc.core.eddn_market import EddnMarketCache, write_buffers
from edc.core.station_pads import extract_station_info
from edc.core.rare_commodities import RareCommodityTable
from edc.core.bounty_scanner import scan_active_bounties
from edc.core.bgs_conflicts import squadron_faction_name
from edc.core.combat_bond_scanner import scan_unredeemed_combat_total
from edc.core.materials_scanner import scan_latest_materials
from edc.core.notoriety_scanner import scan_latest_notoriety
from edc.core.rank_scanner import scan_latest_rank_progress
from edc.core.squadron_scanner import scan_squadron_status
from edc.core.carrier_scanner import scan_carrier_status
from edc.core.mission_scanner import scan_active_missions
from edc.ui.panels.squadron_panel import SquadronPanel
from edc.ui.panels.mining_panel import MiningPanel
from edc.ui.panels.market_panel import MarketPanel, normalize_commodity_name
from edc.ui.panels.trade_route_panel import TradeRoutePanel
from edc.ui.panels.player_faction_panel import PlayerFactionPanel
from edc.ui import formatting as fmt
from edc.audio.tts_engine import TTSEngine
from edc.audio.voice_commands import VoiceCommandListener
from edc.core.ship_command_dispatcher import ShipCommandDispatcher
from edc.ui.panels.voice_commands_panel import VoiceCommandsPanel
from edc.audio.handlers.exploration import ExplorationPhrases
from edc.audio.handlers.exobiology import ExobiologyPhrases
from edc.audio.handlers.combat import CombatPhrases
from edc.audio.handlers.status import StatusPhrases
from edc.audio.handlers.powerplay import PowerPlayPhrases
from typing import Any, Dict, List, Optional

from persistence.database import Database
from persistence.schema import SCHEMA_SQL
from persistence.repository import Repository

from edc.core.session_ledger import SessionLedger
from edc.core.engineer_progress_store import EngineerProgressStore

log = logging.getLogger("edc.ui.main")


class _SpanshEnrichWorker(QObject):
    finished = pyqtSignal(list, str, object)  # object for system_address — avoids 32-bit C++ int truncation

    def __init__(self, system_name: str, system_address: int):
        super().__init__()
        self._system_name    = system_name
        self._system_address = system_address

    def run(self):
        bodies, error = _SpanshClient().fetch_system_bodies(self._system_name, self._system_address)
        self.finished.emit(bodies, error, self._system_address)


class _SpanshRingWorker(QObject):
    finished = pyqtSignal(list, str, object)  # rings, error, system_address

    def __init__(self, system_address: int):
        super().__init__()
        self._system_address = system_address

    def run(self):
        rings, error = _SpanshClient().fetch_system_rings(self._system_address)
        self.finished.emit(rings, error, self._system_address)


class _EdsmPowerPlayRefreshWorker(QObject):
    finished = pyqtSignal(bool)

    def __init__(self, cache: EdsmPowerPlayCache):
        super().__init__()
        self._cache = cache

    def run(self):
        ok = self._cache.refresh()
        self.finished.emit(ok)


class _MarketPruneWorker(QObject):
    """
    Deletes stale (>30d) market_prices rows — potentially slow at
    galaxy-wide scale (millions of rows), so this must never run on the UI
    thread. Opens its own connection per the project's cross-thread SQLite
    rule.

    Deliberately does NOT also VACUUM/reclaim disk space here. VACUUM
    needs an EXCLUSIVE lock on the whole file — running it automatically
    on every startup blocked the main thread's own routine journal writes
    (a different connection to the same file) while it held that lock,
    confirmed live as an app freeze for as long as VACUUM took to rewrite
    a multi-GB database. Reclaiming space is now Settings' explicit
    "Compact Database Now" button (_MarketVacuumWorker) instead, so it
    only ever runs when the user has chosen to eat that cost right now.
    """
    finished = pyqtSignal(int)  # deleted_count

    def __init__(self, db_path):
        super().__init__()
        self._db_path = db_path

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        deleted = 0
        try:
            repo = Repository(db)
            deleted = repo.prune_stale_market_prices()
        except Exception:
            log.exception("Market prices prune failed")
        finally:
            db.close()
        self.finished.emit(deleted)


class _MarketVacuumWorker(QObject):
    """
    User-triggered only (Settings' "Compact Database Now") — reclaims disk
    space freed by pruning. See _MarketPruneWorker's docstring for why this
    is never run automatically: VACUUM holds an exclusive lock on the
    whole file for as long as it takes to rewrite it, which blocks any
    other connection's writes (including the main thread's routine
    journal-driven saves) for that entire duration.
    """
    finished = pyqtSignal(bool, str)  # (ok, message)

    def __init__(self, db_path):
        super().__init__()
        self._db_path = db_path

    def run(self):
        from persistence.database import Database

        db = Database(self._db_path)
        try:
            ran_full_vacuum = db.enable_incremental_auto_vacuum()
            db.incremental_vacuum()
            db.ensure_market_prices_indexes()
            note = " (first run — also switched to incremental auto-vacuum)" if ran_full_vacuum else ""
            self.finished.emit(True, f"Database compacted{note}.")
        except Exception as exc:
            log.exception("Database compaction failed")
            self.finished.emit(False, f"Compaction failed: {exc}")
        finally:
            db.close()


class _EddnFlushWorker(QObject):
    """
    Writes a snapshot of EddnMarketCache's buffered EDDN data (popped by
    the main thread via pop_buffers(), which is cheap) plus a WAL
    checkpoint — both used to run directly on the main thread every 45s
    via QTimer, freezing the UI for however long the batch write took.
    Confirmed live: noticeably worse right after docking at a busy
    station's market, since that's exactly when buffered commodity/
    station/faction data peaks. Opens its own connection per the
    project's cross-thread SQLite rule.
    """
    finished = pyqtSignal()

    def __init__(self, db_path, coords, market, factions, stations, codex):
        super().__init__()
        self._db_path = db_path
        self._coords, self._market, self._factions = coords, market, factions
        self._stations, self._codex = stations, codex

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            repo = Repository(db)
            write_buffers(repo, self._coords, self._market, self._factions, self._stations, self._codex)
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            log.exception("Background EDDN flush failed")
        finally:
            db.close()
        self.finished.emit()


class _CanonnRefreshWorker(QObject):
    finished = pyqtSignal(object, str, object, str)  # poi, poi_error, challenge, challenge_error

    def __init__(self, client: CanonnClient, system: str, odyssey: bool, cmdr: str, x: float, y: float, z: float):
        super().__init__()
        self._client = client
        self._system = system
        self._odyssey = odyssey
        self._cmdr = cmdr
        self._x, self._y, self._z = x, y, z

    def run(self):
        poi, poi_error = self._client.get_system_poi(self._system, self._odyssey, self._cmdr)
        challenge, challenge_error = self._client.get_nearest_challenge(self._cmdr, self._x, self._y, self._z)
        self.finished.emit(poi, poi_error, challenge, challenge_error)


class MainWindow(QMainWindow):

    def refresh_from_state(self):
        self._refresh_system_card()
        self._refresh_exploration()
        self._refresh_powerplay()

    def start_auto_watch(self):
        self._auto_start_if_configured()

    def load_last_system_data(self):
        self.system_data_loader.load_last_system_data()
        # This pre-populates state.system_address from the DB before journal
        # replay catches up — which then defeats the "system changed" guard
        # on the Location/FSDJump handler below for the first bootstrap-
        # replayed event (same system, so "unchanged"). Confirmed via live
        # logging: personal/community ring data never loaded on startup
        # without this — so it must also run unconditionally here.
        system_address = getattr(self.state, "system_address", None)
        if isinstance(system_address, int):
            self._load_persisted_rings(system_address)
            self._maybe_start_ring_hotspot_check()

    def _save_exobiology_to_db(self):
        try:
            sys_addr = getattr(self.state, "system_address", None)
            if not isinstance(sys_addr, int):
                return
            for rec in (self.state.exo or {}).values():
                if not isinstance(rec, dict) or not rec.get("Complete"):
                    continue
                if rec.get("DBSaved"):
                    continue
                body_name = rec.get("BodyName") or ""
                genus     = rec.get("Genus") or ""
                species   = rec.get("Species") or ""
                variant   = rec.get("Variant") or ""
                samples   = int(rec.get("Samples") or 3)
                if not (body_name and genus and species and variant):
                    continue
                self.repo.save_exobiology(
                    system_address=sys_addr,
                    body_name=body_name,
                    genus=genus,
                    species=species,
                    variant=variant,
                    samples=samples,
                )
                rec["DBSaved"] = True
        except Exception:
            pass

    def _save_session_ledger(self):
        try:
            self.session_ledger.save(
                {
                    "combat_unsold_total": int(getattr(self.state, "combat_unsold_total", 0) or 0),
                    "exploration_unsold_total_est": int(getattr(self.state, "exploration_unsold_total_est", 0) or 0),
                    "exobiology_unsold_total_est": int(getattr(self.state, "exobiology_unsold_total_est", 0) or 0),
                }
            )
        except Exception:
            pass

    def _save_faction_snapshots(self):
        system_address = getattr(self.state, "system_address", None)
        factions = getattr(self.state, "factions", None) or []
        if not isinstance(system_address, int) or not factions:
            return

        controlling = (getattr(self.state, "controlling_faction", None) or "").strip()
        today = date.today().isoformat()
        try:
            for f in factions:
                if not isinstance(f, dict):
                    continue
                is_controlling = bool(controlling) and f.get("Name") == controlling
                self.repo.save_faction_snapshot(system_address, f, today, is_controlling)
        except Exception:
            log.exception("Failed to save faction snapshots")

    def _save_ring_data(self):
        system_address = getattr(self.state, "system_address", None)
        rings = getattr(self.state, "rings", None) or {}
        if not isinstance(system_address, int) or not rings:
            return
        try:
            for ring_name, rec in rings.items():
                if not isinstance(rec, dict) or rec.get("system_address") != system_address:
                    continue
                self.repo.save_ring(
                    system_address=system_address,
                    ring_name=ring_name,
                    parent_body=rec.get("parent_body"),
                    ring_class=rec.get("ring_class") or "",
                    distance_ls=rec.get("distance_ls"),
                    scanned=bool(rec.get("scanned")),
                    hotspots=rec.get("hotspots") or None,
                )
        except Exception:
            log.exception("Failed to save ring data")

    def _load_persisted_rings(self, system_address: int) -> None:
        """
        Backfills state.rings from previously-persisted scan data on arrival
        — so a ring scanned in an earlier session shows up immediately, not
        only after re-scanning it this session. Never overwrites a ring
        already known in-memory (e.g. from a bootstrap tail-replay of this
        same journal file moments earlier).
        """
        try:
            for rec in self.repo.get_rings_for_system(system_address):
                ring_name = rec.get("ring_name")
                if not ring_name or ring_name in self.state.rings:
                    continue
                self.state.rings[ring_name] = {
                    "system_address": system_address,
                    "parent_body": rec.get("parent_body"),
                    "ring_class": rec.get("ring_class") or "",
                    "distance_ls": rec.get("distance_ls"),
                    "scanned": bool(rec.get("scanned")),
                    "hotspots": rec.get("hotspots") or [],
                }
        except Exception:
            log.exception("Failed to load persisted ring data for system_address=%s", system_address)

    def _save_station_info(self, evt: dict):
        """
        Ground-truth landing pad data from our own Docked event — the most
        reliable source, better than EDDN's stationType heuristic. Fires
        for every station we personally dock at, not just ones we trade at.
        """
        info = extract_station_info(evt)
        if not info:
            return
        try:
            self.repo.save_station_info(
                market_id=info["market_id"],
                station_name=info["station_name"],
                system_name=info["system_name"],
                station_type=info["station_type"],
                pads_small=info["pads_small"],
                pads_medium=info["pads_medium"],
                pads_large=info["pads_large"],
                last_visited=info["timestamp"],
                station_services=info["station_services"],
                station_faction=info["station_faction"],
            )
        except Exception:
            log.exception("Failed to save station info")

    def _save_colonisation_depot(self, evt: dict):
        """
        ColonisationConstructionDepot only fires in our own journal when we
        personally dock at the depot and open its contribution screen — no
        EDDN schema exists for this (confirmed against EDCD/EDDN's schema
        repo), so it can't be crowdsourced like market/station data. The
        event itself carries no system/station name, only MarketID — pulled
        from current state instead, same as the Market event's own handling.
        """
        market_id = evt.get("MarketID")
        if not isinstance(market_id, int):
            return
        system_name = getattr(self.state, "system", None) or ""
        station_name = getattr(self.state, "current_market_station", None) or ""
        if not system_name or not station_name:
            return
        system_address = getattr(self.state, "system_address", None)

        resources = []
        for r in (evt.get("ResourcesRequired") or []):
            if not isinstance(r, dict):
                continue
            resources.append({
                "name": r.get("Name_Localised") or r.get("Name") or "",
                "required": r.get("RequiredAmount"),
                "provided": r.get("ProvidedAmount"),
                "payment": r.get("Payment"),
            })

        from datetime import datetime, timezone
        try:
            self.repo.save_colonisation_depot_visit(
                market_id=market_id,
                system_address=system_address,
                system_name=system_name,
                station_name=station_name,
                progress=evt.get("ConstructionProgress"),
                complete=bool(evt.get("ConstructionComplete")),
                resources_json=json.dumps(resources),
                timestamp=evt.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            log.exception("Failed to save colonisation depot data")

    def _on_market_destination_selected(self, system_name: str, station_name: str, commodity: str, mode: str):
        """
        Market tab — clicking a Station/System cell in the results table
        pins that destination (persisted to disk so a crash/restart shows
        it again) until Docked at that exact station clears it.
        """
        self._pinned_destination = {
            "system_name": system_name,
            "station_name": station_name,
            "commodity": commodity,
            "mode": mode,
        }
        self.market_destination_store.save(system_name, station_name, commodity, mode)
        self._refresh_pinned_destination_display()

    def _maybe_clear_pinned_destination(self, docked_station_name):
        if not self._pinned_destination or not isinstance(docked_station_name, str):
            return
        if docked_station_name.strip().lower() != self._pinned_destination["station_name"].strip().lower():
            return
        self._pinned_destination = None
        self.market_destination_store.clear()
        self._refresh_pinned_destination_display()

    def _on_pinned_destination_dismissed(self):
        # "Mark Reached" link on the Overview banner — manual clear for
        # when Docked-matching won't fire (changed plans, docked elsewhere,
        # or just want to reset it without actually flying there).
        if not self._pinned_destination:
            return
        self._pinned_destination = None
        self.market_destination_store.clear()
        self._refresh_pinned_destination_display()

    def _refresh_pinned_destination_display(self):
        try:
            self.overview_panel.set_pinned_destination(self._pinned_destination)
        except Exception:
            log.exception("Failed to update pinned destination display")

    def _seed_commodity_names_from_market_json(self):
        """
        Market.json persists on disk from whenever the commodity screen was
        last opened — possibly a previous session, at a station we're no
        longer docked at. Read it once at startup just to seed the
        autocomplete name list; deliberately does NOT touch
        state.current_market_* (that has "currently docked here" meaning
        elsewhere, e.g. Trade Opportunities, and this data may be stale).
        """
        journal_dir = getattr(self.cfg, "journal_dir", None)
        if not journal_dir:
            return
        market_path = Path(journal_dir) / "Market.json"
        try:
            if not market_path.exists():
                return
            data = json.loads(market_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            log.exception("Failed to read Market.json for commodity name seeding")
            return
        if not isinstance(data, dict):
            return
        name_pairs = []
        for it in (data.get("Items") or []):
            if not isinstance(it, dict):
                continue
            name = it.get("Name_Localised") or it.get("Name") or ""
            if not name:
                continue
            name_pairs.append((normalize_commodity_name(name), name))
        try:
            self.repo.save_commodity_names_batch(name_pairs)
        except Exception:
            log.exception("Failed to seed commodity display names")

    def _load_current_market(self):
        """
        Reads Market.json (written by the game alongside the journal
        whenever the commodity screen is opened) into state.current_market_*.
        """
        journal_dir = getattr(self.cfg, "journal_dir", None)
        if not journal_dir:
            return
        market_path = Path(journal_dir) / "Market.json"
        try:
            if not market_path.exists():
                return
            data = json.loads(market_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            log.exception("Failed to read Market.json")
            return

        if not isinstance(data, dict):
            return

        self.state.current_market_id = data.get("MarketID")
        self.state.current_market_station = data.get("StationName")
        self.state.current_market_system = data.get("StarSystem")

        items = []
        name_pairs = []
        for it in (data.get("Items") or []):
            if not isinstance(it, dict):
                continue
            name = it.get("Name_Localised") or it.get("Name") or ""
            if not name:
                continue
            items.append({
                "name": name,
                "category": it.get("Category_Localised") or it.get("Category") or "",
                "buy_price": it.get("BuyPrice") or 0,
                "sell_price": it.get("SellPrice") or 0,
                "demand": it.get("Demand") or 0,
                "stock": it.get("Stock") or 0,
            })
            name_pairs.append((normalize_commodity_name(name), name))
        self.state.current_market_items = items
        try:
            self.repo.save_commodity_names_batch(name_pairs)
        except Exception:
            log.exception("Failed to save commodity display names")

    def _load_cargo_inventory(self):
        """
        Reads Cargo.json — per the journal manual, only the FIRST "Cargo"
        event in a session carries the Inventory array inline; every
        subsequent one is just a bare notification that the file changed,
        so this must be re-read from disk every time to stay current.
        """
        journal_dir = getattr(self.cfg, "journal_dir", None)
        if not journal_dir:
            return
        cargo_path = Path(journal_dir) / "Cargo.json"
        try:
            if not cargo_path.exists():
                return
            data = json.loads(cargo_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            log.exception("Failed to read Cargo.json")
            return

        if not isinstance(data, dict):
            return

        inv = data.get("Inventory")
        if isinstance(inv, list):
            self.state.cargo_inventory = inv

    def _planet_value_class_name(self, planet_class: str) -> str:
        pc = (planet_class or "").strip()
        mapping = {
            "Earthlike body": "Earth-like World",
            "High metal content body": "High Metal Content Planet",
            "Rocky body": "Rocky Body",
            "Rocky ice body": "Rocky Ice Body",
            "Water world": "Water World",
            "Ammonia world": "Ammonia World",
        }
        return mapping.get(pc, pc)

    # --- add inside class MainWindow, near other helper methods ---
    def _format_star_class_label(self, star_class: str | None) -> str:
        if not isinstance(star_class, str) or not star_class.strip():
            return ""

        sc = star_class.strip().upper()

        scoopable = {"O", "B", "A", "F", "G", "K", "M"}
        brown_dwarfs = {"L", "T", "Y"}

        if sc in scoopable:
            return f"{sc} • Scoopable"
        if sc in brown_dwarfs:
            return f"{sc} • Brown Dwarf"
        if sc.startswith("D"):
            return f"{sc} • White Dwarf"
        if sc in {"N", "NEUTRON"}:
            return f"{sc} • Neutron Star"

        return sc

    def _get_star_class_label_and_color(self, star_class: str | None) -> tuple[str, str]:
        if not isinstance(star_class, str) or not star_class.strip():
            return "", ""

        sc = star_class.strip().upper()

        scoopable = {"O", "B", "A", "F", "G", "K", "M"}
        brown_dwarfs = {"L", "T", "Y"}

        if sc in scoopable:
            return f"{sc} • Scoopable", "#7CFC98"   # soft green
        if sc in brown_dwarfs:
            return f"{sc} • Brown Dwarf", "#FFCC66" # amber
        if sc.startswith("D"):
            return f"{sc} • White Dwarf", "#FFB366" # orange-amber
        if sc in {"N", "NEUTRON"}:
            return f"{sc} • Neutron Star", "#FF9966" # deeper orange

        return sc, "#D3D3D3"  # neutral fallback

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def _on_exploration_min_value_changed(self, text: str):
        if hasattr(self, "min_value_label"):
            self.min_value_label.setText(text)

    def _on_exo_min_value_changed(self, text: str):
        if hasattr(self, "exo_min_label"):
            self.exo_min_label.setText(text)

    def __init__(self, cfg_store, cfg, auto_start: bool = True):
        super().__init__()
        self.cfg_store = cfg_store
        self.cfg = cfg

        self.setWindowTitle("EDChronicle")
        self.setWindowIcon(QIcon("assets/edc_icon.ico"))
        self.resize(1200, 700)

        if getattr(cfg, "always_on_top", False):
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self.state = GameState()

        # Canonical paths: app_dir for shipped assets, settings_dir for writable JSON/caches.
        app_dir = Path(getattr(self.cfg_store, "app_dir", Path.cwd()))
        settings_base = Path(getattr(self.cfg_store, "settings_dir", app_dir / "settings"))

        data_dir = app_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(data_dir / "edhelper.db")
        self.db.executescript(SCHEMA_SQL)
        self.db.run_migrations()
        self.repo = Repository(self.db)

        self.session_ledger = SessionLedger(data_dir / "session_ledger.json")
        ledger = self.session_ledger.load()

        self.engineer_progress_store = EngineerProgressStore(data_dir / "engineer_progress.json")
        self.state.engineer_progress = self.engineer_progress_store.load()
        self.state.exploration_unsold_total_est = int(ledger.get("exploration_unsold_total_est", 0) or 0)
        self.state.exobiology_unsold_total_est = int(ledger.get("exobiology_unsold_total_est", 0) or 0)

        # Active bounties must survive across app restarts and journal-file
        # boundaries (a real in-game bounty doesn't clear just because the
        # app restarted) — reconstructed by scanning full journal history
        # rather than persisted ledger state, which only tracks live changes
        # seen while the app happened to be running.
        try:
            self.state.active_bounties = scan_active_bounties(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else {}
        except Exception:
            log.exception("Failed to scan journal history for active bounties")
            self.state.active_bounties = {}

        # Same reasoning as active_bounties: session_ledger.json only captures
        # what got saved before the app's last exit — a gap that showed up
        # for real (a run spanning 3 journal files under-counted unredeemed
        # combat bonds by ~795k cr after an app restart mid-session). Full
        # journal replay is authoritative and self-heals regardless of
        # whether prior sessions saved cleanly.
        try:
            self.state.combat_unsold_total = scan_unredeemed_combat_total(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else 0
        except Exception:
            log.exception("Failed to scan journal history for unredeemed combat bonds")
            self.state.combat_unsold_total = int(ledger.get("combat_unsold_total", 0) or 0)

        # Same reasoning as active_bounties: the live bootstrap only re-reads
        # the tail of the current journal, which can miss the Materials
        # event (fires at journal start / Materials panel open) on a long
        # session, leaving held-material counts at 0 despite real stock.
        try:
            materials = scan_latest_materials(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else ({}, {}, {})
        except Exception:
            log.exception("Failed to scan journal history for materials")
            materials = ({}, {}, {})
        self.state.materials_raw, self.state.materials_manufactured, self.state.materials_encoded = materials

        # Same reasoning as active_bounties: the live bootstrap only re-reads
        # the tail of the current journal, which can miss the Statistics
        # event that carries Notoriety if it fell outside that window.
        try:
            notoriety_rec = scan_latest_notoriety(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else None
        except Exception:
            log.exception("Failed to scan journal history for notoriety")
            notoriety_rec = None
        if notoriety_rec:
            self.state.notoriety = notoriety_rec.get("notoriety")
            self.state.notoriety_timestamp = notoriety_rec.get("timestamp")

        # Same reasoning again: Rank/Progress fire once at session login,
        # which a long play session can push outside the tail-replay window.
        try:
            rank_rec, progress_rec = scan_latest_rank_progress(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else (None, None)
        except Exception:
            log.exception("Failed to scan journal history for rank/progress")
            rank_rec, progress_rec = None, None
        if rank_rec:
            self.state.ranks = rank_rec
        if progress_rec:
            self.state.rank_progress = progress_rec

        try:
            squadron_rec = scan_squadron_status(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else None
        except Exception:
            log.exception("Failed to scan journal history for squadron status")
            squadron_rec = None
        if squadron_rec:
            self.state.squadron_name = squadron_rec.get("name")
            self.state.squadron_rank = squadron_rec.get("rank")
            self.state.squadron_rank_history = squadron_rec.get("rank_history") or []
            self.state.squadron_trophies = int(squadron_rec.get("trophies", 0) or 0)
            self.state.squadron_status = squadron_rec.get("status")
            self.state.squadron_status_timestamp = squadron_rec.get("status_timestamp")

        # Same reasoning again: a carrier's last CarrierStats/CarrierJump may
        # have happened in an earlier session, outside the live bootstrap's
        # tail-replay window.
        try:
            carrier_rec = scan_carrier_status(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else None
        except Exception:
            log.exception("Failed to scan journal history for carrier status")
            carrier_rec = None
        if carrier_rec:
            self.state.carrier_owned_market_id = carrier_rec.carrier_owned_market_id
            self.state.carrier_market_id = carrier_rec.carrier_market_id
            self.state.carrier_callsign = carrier_rec.carrier_callsign
            self.state.carrier_name = carrier_rec.carrier_name
            self.state.carrier_docking_access = carrier_rec.carrier_docking_access
            self.state.carrier_allow_notorious = carrier_rec.carrier_allow_notorious
            self.state.carrier_fuel_level = carrier_rec.carrier_fuel_level
            self.state.carrier_jump_range_curr = carrier_rec.carrier_jump_range_curr
            self.state.carrier_jump_range_max = carrier_rec.carrier_jump_range_max
            self.state.carrier_pending_decommission = carrier_rec.carrier_pending_decommission
            self.state.carrier_space_usage = carrier_rec.carrier_space_usage
            self.state.carrier_finance = carrier_rec.carrier_finance
            self.state.carrier_current_system = carrier_rec.carrier_current_system
            self.state.carrier_next_jump_system = carrier_rec.carrier_next_jump_system
            self.state.carrier_next_jump_body = carrier_rec.carrier_next_jump_body
            self.state.carrier_trade_orders = carrier_rec.carrier_trade_orders
            self.state.squadron_carrier = carrier_rec.squadron_carrier

        try:
            self.state.active_missions = scan_active_missions(Path(self.cfg.journal_dir)) \
                if getattr(self.cfg, "journal_dir", None) else {}
        except Exception:
            log.exception("Failed to scan journal history for active missions")
            self.state.active_missions = {}

        self._seed_commodity_names_from_market_json()

        # Load value tables from the canonical app_dir only (no Path.cwd fallbacks).
        self.planet_values = PlanetValueTable.load_from_paths(settings_base / "planet_values.json")
        self.exo_values = ExoValueTable.load_from_paths(settings_base / "exo_values.json")
        self.pp_activities = PowerPlayActivityTable.load_from_paths(settings_base / "powerplay_activities.json")

        log.info("MainWindow paths: app_dir=%s settings_dir=%s", str(app_dir), str(settings_base))

        self.external_intel = ExternalIntel(settings_base)
        self.item_catalog = ItemCatalog(settings_base)
        self.farming_locations = FarmingLocations(settings_base)
        self.edsm_powerplay = EdsmPowerPlayCache(settings_base)
        self._edsm_powerplay_thread: QThread | None = None
        self._edsm_powerplay_worker: _EdsmPowerPlayRefreshWorker | None = None
        self._market_prune_thread: QThread | None = None
        self._market_prune_worker: _MarketPruneWorker | None = None
        self._market_vacuum_thread: QThread | None = None
        self._market_vacuum_worker: _MarketVacuumWorker | None = None

        self.eddn_publisher = EddnPublisher()
        self.eddn_publisher.start()

        self.canonn_client = CanonnClient()
        self._canonn_poi: SystemPoi | None = None
        self._canonn_challenge: dict | None = None
        self._canonn_thread: QThread | None = None
        self._canonn_worker: _CanonnRefreshWorker | None = None
        self._spansh_rings_by_system: Dict[int, List[dict]] = {}
        self.engineering_blueprints = EngineeringBlueprintTable(settings_base)
        self.experimental_effects = ExperimentalEffectsTable(settings_base)
        self.rare_commodities = RareCommodityTable(settings_base)
        self.engineering_wishlist_store = EngineeringWishlist(data_dir / "engineering_wishlist.json")
        self.odyssey_engineering = OdysseyEngineeringTable(settings_base)
        self.odyssey_wishlist_store = OdysseyWishlist(data_dir / "odyssey_engineering_wishlist.json")
        self.market_destination_store = MarketDestinationStore(data_dir / "market_destination.json")
        self.megaship_tracker = MegashipTracker(data_dir / "megaships_seen.json")
        try:
            if getattr(self.cfg, "journal_dir", None):
                self.megaship_tracker.merge_seen(scan_visited_megaships(Path(self.cfg.journal_dir)))
        except Exception:
            log.exception("Failed to scan journal history for visited megaships")
        self._pinned_destination: dict | None = self.market_destination_store.load()
        self.faction_refresh_tracker = FactionRefreshTracker(data_dir / "faction_refresh.json")
        self.eddn_powerplay = EddnPowerPlayCache(settings_base)
        self._eddn_worker: EddnPowerPlayWorker | None = None
        self._eddn_thread: QThread | None = None
        self._eddn_save_timer = QTimer(self)
        self._eddn_save_timer.setInterval(2 * 60 * 1000)  # persist periodically, not on every sighting
        self._eddn_save_timer.timeout.connect(self.eddn_powerplay.save)
        self._edsm_powerplay_retry_timer = QTimer(self)
        self._edsm_powerplay_retry_timer.setInterval(10 * 60 * 1000)  # retry every 10 min until fresh
        self._edsm_powerplay_retry_timer.timeout.connect(self._maybe_start_edsm_powerplay_refresh)

        self.eddn_market_cache = EddnMarketCache(self.repo)
        self._market_flush_timer = QTimer(self)
        self._market_flush_timer.setInterval(45 * 1000)  # batch-write buffered EDDN market data periodically
        self._market_flush_timer.timeout.connect(self._on_market_flush_tick)
        self._flush_thread: QThread | None = None
        self._flush_worker: _EddnFlushWorker | None = None

        self._player_faction_refresh_timer = QTimer(self)
        # BGS ticks server-side once a day — this only needs to be frequent
        # enough to eventually surface EDDN-sourced changes to systems the
        # player hasn't personally visited, not "live". Arriving in a
        # tracked system triggers an immediate refresh separately.
        self._player_faction_refresh_timer.setInterval(20 * 60 * 1000)
        self._player_faction_refresh_timer.timeout.connect(self._refresh_player_faction)
        self._player_faction_refresh_timer.start()

        self.engine = EventEngine(
            self.state,
            settings_base,
            planet_values=self.planet_values,
            exo_values=self.exo_values,
            external_intel=self.external_intel,
        )

        self.system_data_loader = SystemDataLoader(
            state=self.state,
            repo=self.repo,
            planet_values=self.planet_values,
            on_refresh_exploration=self._refresh_exploration,
            on_refresh_materials_shortlist=self._refresh_materials_shortlist,
            on_refresh_exobiology=self._refresh_exobiology,
            planet_value_class_name_fn=self._planet_value_class_name,
            on_enrichment_needed=self._maybe_start_spansh_enrichment,
        )

        self.watcher_controller = WatcherController(
            on_event=self._on_event,
            on_status=self._on_status,
            on_error=self._on_error,
        )

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        # ===============================
        # Elite Header Bar
        # ===============================
        self.header_bar = QLabel("EDChronicle")
        self.header_bar.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #FF8C00;
            padding-left: 12px;
            padding-top: 8px;
        """)

        # ---- Header layout (title left, session tracker right) ----
        self.hud = QLabel("Not connected")
        self.status = QLabel("Status: idle")

        left_header = QVBoxLayout()
        left_header.setContentsMargins(0, 0, 0, 0)
        left_header.setSpacing(6)
        left_header.addWidget(self.header_bar)
        left_header.addWidget(self.hud)
        left_header.addWidget(self.status)

        # Session tracker panel
        self.session_panel = QLabel()
        self.session_panel.setText("Session\nKills: 0\nBounties: 0 cr")
        self.session_panel.setTextFormat(Qt.TextFormat.RichText)
        self.session_panel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.session_panel.setStyleSheet("""
            color: #FF8C00;
            font-weight: bold;
            padding-left: 10px;
            padding-top: 4px;
        """)

        # Route tracker panel
        self.route_panel = QLabel()
        self.route_panel.setText("Route\nNext: -\nJumps: -")
        self.route_panel.setTextFormat(Qt.TextFormat.RichText)
        self.route_panel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.route_panel.setStyleSheet("""
            color: #87CEFA;
            font-weight: bold;
            padding-left: 10px;
            padding-top: 4px;
        """)

        right_header = QHBoxLayout()
        right_header.setContentsMargins(0, 0, 0, 0)
        right_header.setSpacing(10)
        right_header.addWidget(self.route_panel)
        right_header.addWidget(self.session_panel)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        header_layout.addLayout(left_header, 1)
        header_layout.addLayout(right_header, 0)

        layout.addLayout(header_layout)

        self.min_value_label = QLabel()
        self.min_value_slider = QSlider()
        self.min_value_slider.setOrientation(Qt.Orientation.Horizontal)
        self.min_value_slider.setMinimum(0)
        # 0..200 => 0.0M .. 20.0M in steps of 0.1M (100k credits)
        self.min_value_slider.setMaximum(200)
        self.min_value_slider.setValue(int(getattr(self.cfg, "min_planet_value_100k", 5) or 5))
        self.min_value_slider.valueChanged.connect(self._on_min_value_changed)

        # Exobiology filter: "high value" threshold (M cr)
        self.exo_min_label = QLabel()
        self.exo_min_slider = QSlider()
        self.exo_min_slider.setOrientation(Qt.Orientation.Horizontal)
        self.exo_min_slider.setMinimum(0)
        self.exo_min_slider.setMaximum(50)
        self.exo_min_slider.setValue(int(getattr(self.cfg, "exo_high_value_m", 2) or 2))
        self.exo_min_slider.valueChanged.connect(self._on_exo_min_changed)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        # === ELITE SIDEBAR LAYOUT ===
        main_layout = QHBoxLayout()
        layout.addLayout(main_layout)

        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setFixedWidth(150)
        self.sidebar.setIconSize(QSize(20, 20))
        self.sidebar.setSpacing(2)
        # Scoped to this instance only — the global QListWidget::item rule
        # (12px padding) is generous for other lists in the app, but here it
        # was eating width that should go to the main content area instead.
        self.sidebar.setStyleSheet("QListWidget::item { padding: 8px 10px; font-size: 12px; }")

        # Stacked content
        self.stack = QStackedWidget()

        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stack, 1)

        # Overview tab (System Card)
        self.overview_panel = OverviewPanel()
        self.overview_panel.navigate_to.connect(self.sidebar.setCurrentRow)
        self.overview_panel.set_pinned_destination(self._pinned_destination)
        self.overview_panel.destination_dismissed.connect(self._on_pinned_destination_dismissed)

        # Exploration tab
        self.exploration_panel = ExplorationPanel()
        self.exploration_panel.min_value_changed.connect(
            self._on_exploration_min_value_changed
        )
        self.exploration_panel.body_clicked.connect(self._open_planet_detail)

        # Exobiology tab
        self.exobiology_panel = ExobiologyPanel()
        self.exobiology_panel.exo_min_value_changed.connect(
            self._on_exo_min_value_changed
        )

        # PowerPlay tab
        self.powerplay_panel = PowerplayPanel(edsm_powerplay=self.edsm_powerplay, eddn_powerplay=self.eddn_powerplay)

        # Engineering tab
        self.engineering_panel = EngineeringPanel(
            self.engineering_blueprints, self.engineering_wishlist_store,
            self.odyssey_engineering, self.odyssey_wishlist_store,
            self.experimental_effects,
        )

        # Fleet Carrier tab
        self.fleet_carrier_panel = FleetCarrierPanel()

        # Mining tab
        self.mining_panel = MiningPanel(self.repo)

        # Market tab
        self.market_panel = MarketPanel(self.repo, self.rare_commodities, edsm_powerplay=self.edsm_powerplay)
        self.trade_route_panel = TradeRoutePanel(self.repo, edsm_powerplay=self.edsm_powerplay)
        self.mining_panel.sell_search_requested.connect(self._on_mining_sell_search_requested)
        self.market_panel.destination_selected.connect(self._on_market_destination_selected)

        # Player Faction tab
        self.player_faction_panel = PlayerFactionPanel(self.repo, self.faction_refresh_tracker)

        # Squadron tab
        self.squadron_panel = SquadronPanel(self.repo)
        self.squadron_panel.buy_search_requested.connect(self._on_squadron_buy_search_requested)

        # Combat tab (stub)
        self.combat_panel = CombatPanel()

        # Intel tab (external / advisory)
        self.intel_panel = IntelPanel()

        self.shiplocker_panel = ShiplockerPanel()

        self.materials_panel = MaterialsPanel()

        # Voice Commands tab
        _vc_config_path = app_dir / "settings" / "voice_commands.json"
        self.voice_commands_panel = VoiceCommandsPanel(_vc_config_path, app_dir / "models")
        self.voice_commands_panel.commands_changed.connect(self._on_voice_commands_config_changed)

        # Settings tab
        tab_settings = QWidget()
        st = QVBoxLayout(tab_settings)

        st.addWidget(QLabel("Settings"))

        st.addWidget(QLabel("Elite Dangerous Journal Folder:"))
        row = QHBoxLayout()
        self.settings_journal_edit = QLineEdit(self.cfg.journal_dir or "")
        btn_browse = QPushButton("Browse…")
        row.addWidget(self.settings_journal_edit)
        row.addWidget(btn_browse)
        st.addLayout(row)

        st.addWidget(QLabel("Exploration filter: minimum planet value (M cr)"))
        row2 = QHBoxLayout()
        row2.addWidget(self.min_value_slider)
        row2.addWidget(self.min_value_label)
        st.addLayout(row2)

        st.addWidget(QLabel("Exobiology: high-value threshold (M cr)"))
        row3 = QHBoxLayout()
        row3.addWidget(self.exo_min_slider)
        row3.addWidget(self.exo_min_label)
        st.addLayout(row3)

        from PyQt6.QtWidgets import QCheckBox

        # --- Commander Assist (TTS) ---
        self.tts_enabled_check = QCheckBox("Enable Commander Assist (text-to-speech)")
        self.tts_enabled_check.setChecked(bool(getattr(self.cfg, "tts_enabled", False)))
        self.tts_enabled_check.toggled.connect(self._on_tts_enabled_changed)
        st.addWidget(self.tts_enabled_check)

        # --- Main voice ---
        st.addWidget(QLabel("Main voice (takes effect on restart after saving)"))
        voice_row = QHBoxLayout()
        self.voice_combo = QComboBox()
        self.voice_combo.currentIndexChanged.connect(self._on_main_voice_changed)
        voice_row.addWidget(self.voice_combo)
        btn_test_voice = QPushButton("Test")
        btn_test_voice.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn_test_voice.clicked.connect(self._test_main_voice)
        voice_row.addWidget(btn_test_voice)
        st.addLayout(voice_row)

        st.addWidget(QLabel("Main voice volume"))
        tts_vol_row = QHBoxLayout()
        self.tts_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.tts_vol_slider.setRange(0, 100)
        self.tts_vol_slider.setValue(int(float(getattr(self.cfg, "tts_volume", 0.9)) * 100))
        self.tts_vol_label = QLabel(f"{self.tts_vol_slider.value()}%")
        self.tts_vol_slider.valueChanged.connect(self._on_tts_volume_changed)
        tts_vol_row.addWidget(self.tts_vol_slider)
        tts_vol_row.addWidget(self.tts_vol_label)
        st.addLayout(tts_vol_row)

        # --- Comms channel ---
        self.comms_enabled_check = QCheckBox("Enable NPC comms chatter (background voice)")
        self.comms_enabled_check.setChecked(bool(getattr(self.cfg, "comms_enabled", False)))
        self.comms_enabled_check.toggled.connect(self._on_comms_enabled_changed)
        st.addWidget(self.comms_enabled_check)

        st.addWidget(QLabel("Comms channel volume"))
        comms_vol_row = QHBoxLayout()
        self.comms_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.comms_vol_slider.setRange(0, 100)
        self.comms_vol_slider.setValue(int(float(getattr(self.cfg, "comms_volume", 0.35)) * 100))
        self.comms_vol_label = QLabel(f"{self.comms_vol_slider.value()}%")
        self.comms_vol_slider.valueChanged.connect(self._on_comms_volume_changed)
        comms_vol_row.addWidget(self.comms_vol_slider)
        comms_vol_row.addWidget(self.comms_vol_label)
        st.addLayout(comms_vol_row)

        # --- Voice commands ---
        self.voice_cmd_check = QCheckBox("Enable voice commands (tab switching by voice)")
        self.voice_cmd_check.setChecked(bool(getattr(self.cfg, "voice_commands_enabled", False)))
        self.voice_cmd_check.toggled.connect(self._on_voice_commands_toggled)
        st.addWidget(self.voice_cmd_check)

        # --- Window behaviour ---
        self.always_on_top_check = QCheckBox("Keep window always on top")
        self.always_on_top_check.setChecked(bool(getattr(self.cfg, "always_on_top", False)))
        self.always_on_top_check.toggled.connect(self._on_always_on_top_changed)
        st.addWidget(self.always_on_top_check)

        # --- EDDN contribution ---
        self.eddn_contribute_check = QCheckBox("Contribute data to EDDN (helps Spansh, EDSM, Inara, etc. stay accurate)")
        self.eddn_contribute_check.setToolTip(
            "Sends a subset of your journal events (jumps, docking, scans, "
            "surface signal scans, carrier jumps, codex entries) to the "
            "public Elite Dangerous Data Network. No personal data beyond "
            "your commander name is included — EDDN obfuscates that before "
            "distributing it further. Off by default."
        )
        self.eddn_contribute_check.setChecked(bool(getattr(self.cfg, "eddn_contribute_enabled", False)))
        self.eddn_contribute_check.toggled.connect(self._on_eddn_contribute_toggled)
        st.addWidget(self.eddn_contribute_check)

        # --- Market search radius ---
        market_row = QHBoxLayout()
        market_label = QLabel("Market search radius:")
        self.market_radius_spin = QSpinBox()
        self.market_radius_spin.setRange(10, 5000)
        self.market_radius_spin.setSingleStep(10)
        self.market_radius_spin.setSuffix(" ly")
        self.market_radius_spin.setValue(int(getattr(self.cfg, "market_search_radius_ly", 100) or 100))
        self.market_radius_spin.valueChanged.connect(self._on_market_radius_changed)
        market_row.addWidget(market_label)
        market_row.addWidget(self.market_radius_spin)
        market_row.addStretch(1)
        st.addLayout(market_row)

        # --- Database compaction (manual — see _on_compact_db_clicked) ---
        st.addWidget(QLabel("Database maintenance"))
        self.compact_db_status_label = QLabel(
            "Stale market data is pruned automatically each day. Reclaiming the freed disk "
            "space and building the Trade Route search index (a one-time speed-up) is a "
            "several-minutes operation that locks the database — run it only when you're "
            "not actively playing, not automatically on every startup."
        )
        self.compact_db_status_label.setWordWrap(True)
        st.addWidget(self.compact_db_status_label)
        compact_row = QHBoxLayout()
        self.compact_db_btn = QPushButton("Compact Database Now")
        self.compact_db_btn.clicked.connect(self._on_compact_db_clicked)
        compact_row.addWidget(self.compact_db_btn)
        compact_row.addStretch(1)
        st.addLayout(compact_row)

        st.addStretch(1)

        # Log tab
        tab_log = QWidget()
        lg = QVBoxLayout(tab_log)
        lg.addWidget(QLabel("Log"))
        lg.addWidget(self.log_box)

        # ── Sidebar/stack registration — alphabetical by tab name, with
        # Overview pinned first (the home tab) and Settings/Log (utility
        # tabs, not content) pinned at the end, regardless of sort order.
        # Panels above are constructed in a dependency-safe order (e.g.
        # Mining before Market, since Market wires into Mining's
        # sell_search_requested signal) that's independent of this display
        # order.
        for widget, name in [
            (self.overview_panel,        "Overview"),
            (self.combat_panel,          "Combat"),
            (self.engineering_panel,     "Engineering"),
            (self.exobiology_panel,      "Exobiology"),
            (self.exploration_panel,     "Exploration"),
            (self.fleet_carrier_panel,   "Fleet Carrier"),
            (self.intel_panel,           "Intel"),
            (self.market_panel,          "Market"),
            (self.materials_panel,       "Materials"),
            (self.mining_panel,          "Mining"),
            (self.shiplocker_panel,      "Odyssey"),
            (self.player_faction_panel,  "Player Faction"),
            (self.powerplay_panel,       "PowerPlay"),
            (self.squadron_panel,        "Squadron"),
            (self.trade_route_panel,     "Trade Routes"),
            (self.voice_commands_panel,  "Voice Cmds"),
        ]:
            self.stack.addWidget(widget)
            self.sidebar.addItem(name)
            if name == "Market":
                self._market_tab_row = self.sidebar.count() - 1
            elif name == "Overview":
                self._overview_tab_row = self.sidebar.count() - 1

        self.stack.addWidget(tab_settings)
        self.sidebar.addItem("Settings")
        self.stack.addWidget(tab_log)
        self.sidebar.addItem("Log")

        btn_browse.clicked.connect(self._browse_journal_dir)
        self.settings_journal_edit.editingFinished.connect(self._on_settings_journal_changed)

        # ---- Intel hint suppression (show once per system change) ----
        self._last_intel_system_key: str = ""

        # ---- UI refresh debounce (journal bursts can be spammy) ----
        self._hud_refresh_pending = False
        self._hud_refresh_timer = QTimer(self)
        self._hud_refresh_timer.setSingleShot(True)
        self._hud_refresh_timer.timeout.connect(self._do_hud_refresh)

        # Sidebar navigation — Overview is the intended home tab regardless
        # of its alphabetical position in the list.
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(self._overview_tab_row)
        self._refresh_hud()
        # QTimer.start() fires its first timeout 20 minutes from now, not
        # immediately — without this, _faction_name (and everything gated
        # on it, e.g. the faction-controlled stations lookup) stays unset
        # for up to 20 minutes after every app start.
        self._refresh_player_faction()
        self._maybe_start_edsm_powerplay_refresh()
        self._maybe_start_market_prune()
        self._start_eddn_listener()
        if self.edsm_powerplay.is_stale():
            self._edsm_powerplay_retry_timer.start()
        if auto_start:
            self._auto_start_if_configured()

        self.tts = TTSEngine(
            rate=getattr(self.cfg, "tts_rate", 175),
            volume=getattr(self.cfg, "tts_volume", 0.9),
            voice_index=getattr(self.cfg, "tts_voice_index", 0),
        )
        self.tts.load_from_config(self.cfg)
        self.tts.set_output_device(self.voice_commands_panel.output_device())
        self.tts.start()
        self._tts_spoken_ships: set = set()  # pilot|ship keys spoken this system
        self._tts_spoken_signal_bodies: set = set()  # body keys with signals already announced this system
        self._tts_fss_complete_systems: set = set()  # system_address values already announced "FSS complete"
        self._tts_ship_cooldown_until: float = 0.0  # monotonic timestamp
        self._commander_quip_cooldown_until: float = 0.0
        self._replaying: bool = False  # True during journal bootstrap; suppresses all TTS
        self._enrich_thread: QThread | None = None
        self._enrich_worker: _SpanshEnrichWorker | None = None
        self._ring_gap_thread: QThread | None = None
        self._ring_gap_worker: _SpanshRingWorker | None = None

        # Voice command listener — only started if enabled in settings
        self._voice_cmd_models_dir = app_dir / "models"
        self._voice_cmd_worker = None
        self._voice_cmd_thread = None
        self._ship_dispatcher = ShipCommandDispatcher()
        # "All systems online." must wait for BOTH the full startup sequence
        # (splash closed, window shown, watchers started) AND the voice
        # listener — announcing during the loading screen would falsely
        # signal that all module loads had already completed.
        self._startup_complete   = False
        self._voice_ready        = False
        self._online_announced   = False
        if bool(getattr(self.cfg, "voice_commands_enabled", False)):
            self._start_voice_commands()

        # Elite Dangerous writes a Shutdown journal event on clean exit —
        # treated as "the app can probably close too", but delayed rather
        # than immediate: the app is normally launched before the game (so
        # "game not running yet" is a completely normal state, not a signal
        # to close), and a quick game relaunch shouldn't kill the app out
        # from under the user. Any further live event cancels the countdown.
        self._APP_SHUTDOWN_DELAY_S = 20
        self._shutdown_countdown_timer: QTimer | None = None

        # Populate voice combo now that TTS engine is ready
        self._populate_voice_combo()

    def load_current_system_data(self):
        self.system_data_loader.load_current_system_data()

    def _start_eddn_listener(self):
        if self._eddn_thread and self._eddn_thread.isRunning():
            return

        # Watch EDDN's network-wide Factions array for the squadron-aligned
        # faction, if any — lets us build presence data for systems the
        # player never personally visits (Inara/EDSM do the same thing from
        # the same feed), fixed at listener-start time since this rarely
        # changes mid-session.
        watched_factions = set()
        try:
            overview = self.repo.get_player_faction_overview()
            if overview and overview.get("faction_name"):
                watched_factions.add(overview["faction_name"])
        except Exception:
            log.exception("Failed to load squadron faction name for EDDN watch list")

        self._eddn_worker = EddnPowerPlayWorker(watched_factions=watched_factions)
        self._eddn_thread = QThread()
        self._eddn_worker.moveToThread(self._eddn_thread)
        self._eddn_thread.started.connect(self._eddn_worker.run)
        self._eddn_worker.system_seen.connect(self._on_eddn_system_seen)
        self._eddn_worker.system_coords_seen.connect(self.eddn_market_cache.on_coords_seen)
        self._eddn_worker.commodity_seen.connect(self.eddn_market_cache.on_commodity_message)
        self._eddn_worker.faction_seen.connect(self.eddn_market_cache.on_faction_seen)
        self._eddn_worker.station_seen.connect(self.eddn_market_cache.on_station_seen)
        self._eddn_worker.codex_entry_seen.connect(self.eddn_market_cache.on_codex_entry_seen)
        self._eddn_thread.start()
        self._eddn_save_timer.start()
        self._market_flush_timer.start()
        log.info("EDDN PowerPlay listener started")

    def _stop_eddn_listener(self):
        if self._eddn_worker:
            self._eddn_worker.stop()
        if self._eddn_thread:
            self._eddn_thread.quit()
            self._eddn_thread.wait(2000)
        self._eddn_worker = None
        self._eddn_thread = None
        self._eddn_save_timer.stop()
        self.eddn_powerplay.save()
        self._market_flush_timer.stop()
        self.eddn_market_cache.flush()
        log.info("EDDN PowerPlay listener stopped")

    def _on_eddn_system_seen(self, id64: int, power: str, power_state: str, timestamp: str):
        self.eddn_powerplay.ingest(id64, power, power_state, timestamp)

    def _maybe_start_edsm_powerplay_refresh(self):
        if not self.edsm_powerplay.is_stale():
            return
        if self._edsm_powerplay_thread and self._edsm_powerplay_thread.isRunning():
            return

        log.info("EDSM PowerPlay cache is stale — refreshing in background")
        self._edsm_powerplay_worker = _EdsmPowerPlayRefreshWorker(self.edsm_powerplay)
        self._edsm_powerplay_thread = QThread()
        self._edsm_powerplay_worker.moveToThread(self._edsm_powerplay_thread)
        self._edsm_powerplay_thread.started.connect(self._edsm_powerplay_worker.run)
        self._edsm_powerplay_worker.finished.connect(self._on_edsm_powerplay_refreshed)
        self._edsm_powerplay_worker.finished.connect(self._edsm_powerplay_thread.quit)
        self._edsm_powerplay_thread.start()

    def _on_edsm_powerplay_refreshed(self, ok: bool):
        if ok:
            log.info("EDSM PowerPlay cache refresh complete")
            self._edsm_powerplay_retry_timer.stop()
        else:
            log.warning("EDSM PowerPlay cache refresh failed — will retry later")
            if not self._edsm_powerplay_retry_timer.isActive():
                self._edsm_powerplay_retry_timer.start()

    def _maybe_start_market_prune(self):
        """Once/day is plenty — the prune threshold itself is 30 days, so
        pruning more often would never find anything new to delete."""
        today = date.today().isoformat()
        if getattr(self.cfg, "last_market_prune_date", None) == today:
            return
        if self._market_prune_thread and self._market_prune_thread.isRunning():
            return

        log.info("Pruning stale (>30d) market_prices rows in background")
        self._market_prune_worker = _MarketPruneWorker(self.repo.db.db_path)
        self._market_prune_thread = QThread()
        self._market_prune_worker.moveToThread(self._market_prune_thread)
        self._market_prune_thread.started.connect(self._market_prune_worker.run)
        self._market_prune_worker.finished.connect(self._on_market_prune_finished)
        self._market_prune_worker.finished.connect(self._market_prune_thread.quit)
        self._market_prune_thread.start()

    def _on_market_prune_finished(self, deleted: int) -> None:
        log.info("Market prices prune complete: %d stale rows removed", deleted)
        self.cfg.last_market_prune_date = date.today().isoformat()
        self.cfg_store.save(self.cfg)

    def _on_compact_db_clicked(self) -> None:
        if self._market_vacuum_thread and self._market_vacuum_thread.isRunning():
            return
        self.compact_db_btn.setEnabled(False)
        self.compact_db_status_label.setText(
            "Compacting — this can take several minutes on a large database and will pause "
            "other database activity while it runs. Don't close the app."
        )
        self._market_vacuum_worker = _MarketVacuumWorker(self.repo.db.db_path)
        self._market_vacuum_thread = QThread()
        self._market_vacuum_worker.moveToThread(self._market_vacuum_thread)
        self._market_vacuum_thread.started.connect(self._market_vacuum_worker.run)
        self._market_vacuum_worker.finished.connect(self._on_compact_db_finished)
        self._market_vacuum_worker.finished.connect(self._market_vacuum_thread.quit)
        self._market_vacuum_thread.start()

    def _on_compact_db_finished(self, ok: bool, message: str) -> None:
        self.compact_db_btn.setEnabled(True)
        self.compact_db_status_label.setText(message)

    def _maybe_alert_engineering_materials(self):
        """
        Once per system entry: if a material still short for the wishlist
        has a known farming location in the current system, speak a
        heads-up and show a banner on the Overview tab.
        """
        system_name = (getattr(self.state, "system", None) or "").strip()
        if not system_name:
            return
        try:
            shortfall = self.engineering_panel.missing_materials_for_wishlist()
        except Exception:
            return
        if not shortfall:
            return

        hits = []
        for symbol in shortfall:
            display = self.engineering_blueprints.material_name(symbol)
            for rec in self.farming_locations.get_for_material(display):
                if (rec.get("system") or "").strip().lower() == system_name.lower():
                    hits.append(display)
                    break

        if not hits:
            return

        for display in hits[:2]:  # cap announcements — avoid stacking too many at once
            self.tts.speak(EngineeringPhrases.material_nearby(display), priority=5)
        self.overview_panel.set_engineering_alert(hits)

    def _maybe_start_canonn_refresh(self):
        system_name = getattr(self.state, "system", None) or ""
        if not system_name:
            return
        if self._canonn_thread and self._canonn_thread.isRunning():
            return

        cmdr = getattr(self.state, "commander", None) or ""
        odyssey = bool(getattr(self.state, "odyssey", True))
        x = float(getattr(self.state, "system_x", 0.0) or 0.0)
        y = float(getattr(self.state, "system_y", 0.0) or 0.0)
        z = float(getattr(self.state, "system_z", 0.0) or 0.0)

        self._canonn_worker = _CanonnRefreshWorker(self.canonn_client, system_name, odyssey, cmdr, x, y, z)
        self._canonn_thread = QThread()
        self._canonn_worker.moveToThread(self._canonn_thread)
        self._canonn_thread.started.connect(self._canonn_worker.run)
        self._canonn_worker.finished.connect(self._on_canonn_refreshed)
        self._canonn_worker.finished.connect(self._canonn_thread.quit)
        self._canonn_thread.start()

    def _on_canonn_refreshed(self, poi, poi_error: str, challenge: dict, challenge_error: str):
        if poi_error:
            log.warning("Canonn POI fetch failed: %s", poi_error)
        else:
            self._canonn_poi = poi
        if challenge_error:
            log.warning("Canonn nearest-challenge fetch failed: %s", challenge_error)
        else:
            self._canonn_challenge = challenge
        try:
            self.overview_panel.set_canonn_intel(self._canonn_poi, self._canonn_challenge)
        except Exception:
            log.exception("Failed to update Canonn intel card")
        try:
            self._refresh_exobiology()
        except Exception:
            log.exception("Failed to refresh Exobiology tab with Canonn data")

    def _maybe_start_spansh_enrichment(self):
        system_name    = getattr(self.state, "system",         None) or ""
        system_address = getattr(self.state, "system_address", None)
        log.info("Spansh enrich check: system=%r addr=%s", system_name, system_address)
        if not system_name or not isinstance(system_address, int):
            return

        real_count     = self.repo.count_real_bodies(system_address)
        expected_count = getattr(self.state, "system_body_count", None)
        if isinstance(expected_count, int) and expected_count > 0 and real_count >= expected_count:
            return

        spansh_cached = self.repo.count_spansh_bodies(system_address)
        if spansh_cached > 0:
            return

        if self._enrich_thread and self._enrich_thread.isRunning():
            return

        log.info("Spansh enrich starting for %r (%d)", system_name, system_address)
        self._enrich_worker = _SpanshEnrichWorker(system_name, system_address)
        self._enrich_thread = QThread()
        self._enrich_worker.moveToThread(self._enrich_thread)
        self._enrich_thread.started.connect(self._enrich_worker.run)
        self._enrich_worker.finished.connect(self._on_spansh_enrichment)
        self._enrich_worker.finished.connect(self._enrich_thread.quit)
        self._enrich_thread.start()

    def _on_spansh_enrichment(self, bodies: list, error: str, system_address: int):
        if error:
            log.warning("Spansh enrichment failed: %s", error)
        current_address = getattr(self.state, "system_address", None)
        log.info("Spansh enrichment result: bodies=%d error=%r current_addr=%s worker_addr=%s",
                 len(bodies), error, current_address, system_address)
        if current_address != system_address or not bodies:
            log.info("Spansh enrichment discarded: addr mismatch or empty")
            return
        saved = 0
        for b in bodies:
            self.repo.save_spansh_body(
                system_address=system_address,
                body_name=b["name"],
                planet_class=b.get("planet_class"),
                distance_ls=b.get("distance_ls"),
                estimated_value=b.get("estimated_value"),
                landable=b.get("landable"),
                surface_gravity=b.get("surface_gravity"),
                radius=b.get("radius"),
                mass_em=b.get("mass_em"),
                surface_temperature=b.get("surface_temperature"),
                surface_pressure=b.get("surface_pressure"),
                atmosphere_type=b.get("atmosphere_type"),
                volcanism=b.get("volcanism"),
                tidal_lock=b.get("tidal_lock"),
            )
            saved += 1
        log.info("Spansh enrichment saved %d/%d bodies for address %d", saved, len(bodies), system_address)
        self.system_data_loader.merge_new_spansh_bodies(system_address)

    def _maybe_start_ring_hotspot_check(self):
        system_address = getattr(self.state, "system_address", None)
        if not isinstance(system_address, int):
            return
        if system_address in self._spansh_rings_by_system:
            return  # already checked this system this session
        if self._ring_gap_thread and self._ring_gap_thread.isRunning():
            return

        self._ring_gap_worker = _SpanshRingWorker(system_address)
        self._ring_gap_thread = QThread()
        self._ring_gap_worker.moveToThread(self._ring_gap_thread)
        self._ring_gap_thread.started.connect(self._ring_gap_worker.run)
        self._ring_gap_worker.finished.connect(self._on_ring_hotspot_gap_result)
        self._ring_gap_worker.finished.connect(self._ring_gap_thread.quit)
        self._ring_gap_thread.start()

    def _on_ring_hotspot_gap_result(self, rings: list, error: str, system_address: int):
        if error:
            log.warning("Spansh ring check failed: %s", error)
            return
        self._spansh_rings_by_system[system_address] = rings
        if getattr(self.state, "system_address", None) == system_address:
            self._refresh_hud()
            self._refresh_exploration()

    def _auto_start_if_configured(self):
        """
        Auto-start journal watching on launch if a journal_dir is configured and valid.
        Uses a silent start to avoid modal popups on startup.
        """
        try:
            jd = (self.cfg.journal_dir or "").strip()
            if not jd:
                return
            p = Path(jd)
            if not p.exists():
                self.status.setText("Status: journal folder missing (set in Settings)")
                return
            QTimer.singleShot(0, lambda: self.start_watching(silent=True))
        except Exception:
            pass

    def _on_min_value_changed(self, v: int):
        # persist immediately
        try:
            self.cfg.min_planet_value_100k = int(v)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass
        self.status.setText("Status: settings saved")
        self._refresh_exploration()

    def _on_exo_min_changed(self, v: int):
        # persist immediately
        try:
            self.cfg.exo_high_value_m = int(v)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass
        self.status.setText("Status: settings saved")
        self._refresh_hud()
        self._refresh_exobiology()

    def _browse_journal_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Elite Dangerous Journal Folder")
        if folder:
            self.settings_journal_edit.setText(folder)
            self._on_settings_journal_changed()

    def _on_settings_journal_changed(self):
        path = (self.settings_journal_edit.text() or "").strip()
        self.cfg.journal_dir = path if path else None
        try:
            self.cfg_store.save(self.cfg)
        except Exception:
            pass
        self.status.setText("Status: settings saved")

    def _on_overview_action_link(self, link: str):
        self.overview_panel._on_overview_action_link(link)

    def start_watching(self, silent: bool = False):
        if not self.cfg.journal_dir:
            if not silent:
                QMessageBox.warning(self, "Missing setting", "Set your Journal folder in Settings first.")
            else:
                self.status.setText("Status: missing journal folder (set in Settings)")
            return
        journal_path = Path(self.cfg.journal_dir)
        if not journal_path.exists():
            if not silent:
                QMessageBox.warning(self, "Invalid folder", "That folder doesn't exist.")
            else:
                self.status.setText("Status: journal folder invalid (set in Settings)")
            return
        # Stop any existing watcher cleanly
        self.stop_watching()
        status_path = journal_path / "Status.json"
        self.watcher_controller.start_watching(journal_path, status_path)
        self.status.setText(f"Status: watching {journal_path}")
        self._append(f"Started watching: {journal_path}")
        self._append(f"Started watching status: {status_path}")

    def _pp_state_category(self, pp_state: str, friendly: bool):
        s = (pp_state or "").lower()
        if "unoccupied" in s or "expansion" in s:
            return "Acquisition"
        if friendly:
            return "Reinforcing"
        return "Undermining"
    
    def stop_watching(self):
        self.watcher_controller.stop_watching()

    def _stop_background_threads(self, obj, depth: int = 2, seen: set | None = None) -> None:
        """
        Quits and waits for every still-running QThread reachable from obj
        (its own attributes, dict values like _bucket_dialogs, and nested
        QWidget panels like PowerplayPanel.finder_panel) — confirmed from
        real crash logs this session that a background worker (EDSM/Canonn/
        market/etc. lookup) mid-flight when the app closes gets destroyed
        while still running, a hard Qt fatal. Reflection-based rather than
        a hardcoded thread-attribute list, since this app has ~15 QThread
        workers spread across main_window.py and several panels and new
        ones keep getting added — a fixed list would silently rot.
        """
        if seen is None:
            seen = set()
        if id(obj) in seen or depth < 0 or not hasattr(obj, "__dict__"):
            return
        seen.add(id(obj))
        for attr_name in list(vars(obj)):
            try:
                val = getattr(obj, attr_name, None)
            except Exception:
                continue
            if isinstance(val, QThread):
                if val.isRunning():
                    val.quit()
                    val.wait(3000)
            elif isinstance(val, dict):
                for v in list(val.values()):
                    self._stop_background_threads(v, depth - 1, seen)
            elif isinstance(val, QWidget) and depth > 0:
                self._stop_background_threads(val, depth - 1, seen)

    def closeEvent(self, event):
        import traceback
        log.info("closeEvent triggered:\n%s", "".join(traceback.format_stack()))
        self.stop_watching()
        self._stop_voice_commands()
        self._stop_eddn_listener()
        self._stop_background_threads(self)
        super().closeEvent(event)

    def _on_status(self, msg: str):
        self.status.setText(f"Status: {msg}")
        self._append(msg)

    def _on_error(self, msg: str):
        self._append(f"[ERROR] {msg}")

    def _on_event(self, evt: dict):
        name = evt.get("event", "UNKNOWN")

        if name == "_BootstrapStart":
            self._replaying = True
            return
        if name == "_BootstrapEnd":
            self._replaying = False
            return

        self._append(f"[EVENT] {name}")

        old_system_address = getattr(self.state, "system_address", None)
        self.eddn_publisher.observe(evt)
        state, msgs = self.engine.process(evt)
        self.state = state

        # Bootstrap replay re-reads the tail of the current journal on every
        # app restart to catch up on anything missed — publishing those
        # events again would just be duplicate traffic for data EDDN
        # already received the first time they happened.
        if getattr(self.cfg, "eddn_contribute_enabled", False) and not self._replaying:
            star_pos = (self.state.system_x, self.state.system_y, self.state.system_z)
            self.eddn_publisher.maybe_publish(evt, self.state.system, star_pos, self.state.system_address)

        if name in (
            "Bounty",
            "FactionKillBond",
            "RedeemVoucher",
            "Scan",
            "MultiSellExplorationData",
            "SellExplorationData",
            "ScanOrganic",
            "SellOrganicData",
        ):
            self._save_session_ledger()

        if name in ("Docked", "FSDJump", "Location"):
            self._save_faction_snapshots()

        if name == "Docked":
            self._save_station_info(evt)
            self._maybe_clear_pinned_destination(evt.get("StationName"))

        if name == "ColonisationConstructionDepot":
            self._save_colonisation_depot(evt)
            self._refresh_squadron()

        if name in MISSION_EVENT_NAMES:
            # active_missions itself updates immediately in event_engine.py,
            # but the Player Faction tab's Active Missions card only had a
            # 20-minute recurring timer refreshing it — confirmed live:
            # completing 2 more missions after the first didn't update the
            # displayed count until the next tick.
            self._refresh_player_faction()

        if name == "Market":
            self._load_current_market()
            radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
            self.market_panel.refresh_trade_opportunities(self.state, radius)
            self.market_panel.refresh_commodity_names()
            self.mining_panel.refresh_commodity_names()

        if name == "Undocked":
            # Leaving the station — "what's for sale here" stops being true;
            # the market_panel keeps a separate, longer-lived memory of
            # where to sell anything already in cargo. Must call
            # refresh_trade_opportunities() specifically — refresh() is the
            # cheap path and deliberately doesn't touch that table.
            self.state.current_market_id = None
            self.state.current_market_station = None
            self.state.current_market_system = None
            self.state.current_market_items = []
            radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
            self.market_panel.refresh_trade_opportunities(self.state, radius)

        if name == "Cargo":
            # Only the FIRST "Cargo" event in a session carries the
            # Inventory array inline — every subsequent one is just a bare
            # notification that Cargo.json changed (confirmed in the
            # journal manual), so the file itself must be re-read each time.
            self._load_cargo_inventory()
            self._refresh_market()

        if name == "EngineerProgress":
            self.engineer_progress_store.save(self.state.engineer_progress)

        incoming_system_address = evt.get("SystemAddress")

        if name in ("Location", "FSDJump"):
            if isinstance(incoming_system_address, int) and incoming_system_address != old_system_address:
                self.state.system_address = incoming_system_address
                self._tts_spoken_ships.clear()
                self._tts_spoken_signal_bodies.clear()
                self.load_current_system_data()
                self._load_persisted_rings(incoming_system_address)
                self._maybe_start_spansh_enrichment()
                self._maybe_start_canonn_refresh()
                self._maybe_start_ring_hotspot_check()
                self._maybe_alert_engineering_materials()
                self._refresh_hud()
                self._refresh_exploration()
                # BGS state changes on a daily server tick, not per-event —
                # arriving in a system is the moment the game hands us
                # fresh, authoritative faction data for it. Only that one
                # row needs checking, not a full rebuild of every tracked
                # system (that's left to the coarse timer / tab-visibility).
                self.player_faction_panel.refresh_single_system(incoming_system_address)

        if name == "StartJump" and evt.get("JumpType") == "Hyperspace":
            self._clear_all_panels()

        if name == "SupercruiseDestinationDrop":
            # Confirms an actual visit to this specific destination — a
            # megaship's Ship Uplinks (the real merit source, verified via
            # journal cross-reference) are a fixed, exhaustible set per
            # megaship, so once visited it's done regardless of PP state at
            # the time. More reliable than guessing from FSS detection alone.
            drop_type = evt.get("Type")
            if isinstance(drop_type, str) and drop_type:
                for s in (getattr(self.state, "system_signals", None) or []):
                    if isinstance(s, dict) and s.get("Category") == "Megaship" and s.get("SignalName") == drop_type:
                        self.megaship_tracker.mark_seen(
                            MegashipTracker.key(self.state.system_address, drop_type)
                        )
                        break

        _tts_on = getattr(self.cfg, "tts_enabled", False)
        _tts_events = getattr(self.cfg, "tts_events", {}) or {}
        for m in msgs:
            if m == "refresh_powerplay":
                self._refresh_powerplay()
            elif m.startswith("CCR distance reached for "):
                self._append(m)
                if _tts_on and _tts_events.get("ScanOrganic", False):
                    self.tts.speak(ExobiologyPhrases.ccr_distance_reached(), priority=3)
            elif m.startswith("CCR too close for "):
                self._append(m)
                if _tts_on and _tts_events.get("ScanOrganic", False):
                    self.tts.speak(ExobiologyPhrases.ccr_too_close(), priority=2)
            elif m.startswith("Exobiology complete: "):
                self._append(m)
                self._save_exobiology_to_db()
            else:
                self._append(m)

        if name != "StartJump":
            self._schedule_hud_refresh()

        # Refresh PowerPlay panel when relevant events occur
        if name in ("Location", "FSDJump", "Powerplay", "PowerplayState"):
            self._refresh_powerplay()

        # Refresh exploration panel when signal or scan data arrives
        if name in ("FSSSignalDiscovered", "FSSDiscoveryScan", "SAASignalsFound",
                    "Scan", "FSSBodySignals", "SAAScanComplete"):
            self._refresh_exploration()

        # SAAScanComplete without a matching SAASignalsFound means a ring
        # was fully probed and found to have zero hotspots (confirmed via
        # real journal data — SAASignalsFound only fires when there's at
        # least one signal to report) — must persist that too, or the ring
        # reverts to "not scanned" on the next restart.
        if name in ("Scan", "SAASignalsFound", "SAAScanComplete"):
            self._save_ring_data()

        # Refresh intel panel when signal data, DSS scan, or a fresh BGS
        # snapshot (Docked) arrives
        if name in ("SAASignalsFound", "FSSBodySignals", "Docked"):
            self._refresh_intel()

        if self._replaying:
            return

        if name == "Shutdown":
            self._start_app_shutdown_countdown()
        elif self._shutdown_countdown_timer is not None:
            # Any other live event means the game is active again — the
            # earlier Shutdown wasn't the end of the session after all.
            self._cancel_app_shutdown_countdown()

        tts_text = self._tts_router(name, evt, self.state)

        # Override guardian TTS with uncharted phrase if system not in farming guide
        if name == "FSSBodySignals" and tts_text:
            body = evt.get("BodyName") or ""
            g_sig = int((getattr(self.state, "guardian_signals", {}) or {}).get(body, 0) or 0)
            if g_sig > 0:
                try:
                    all_records = getattr(self.farming_locations, "_records", []) or []
                    known_guardian_sys = {
                        str(r.get("system") or "").lower()
                        for r in all_records
                        if isinstance(r, dict) and r.get("domain") == "guardian" and r.get("system")
                    }
                    sys_lower = (getattr(self.state, "system", None) or "").lower()
                    if sys_lower and known_guardian_sys and sys_lower not in known_guardian_sys:
                        tts_text = ExplorationPhrases.guardian_signals_uncharted(body, g_sig)
                except Exception:
                    pass

        if name == "StartJump":
            self.tts.drain()
            # System-wide NPC comms chatter belongs to the system we're
            # leaving — cut it immediately (queued and currently playing),
            # without touching the main Commander Assist channel above.
            self.tts.stop_comms()

        if tts_text:
            if name == "StartJump":
                _p = self._tts_priority(name)
                QTimer.singleShot(5000, lambda t=tts_text, p=_p: self.tts.speak(t, priority=p))
            elif name in ("FSDJump", "Location", "LoadGame"):
                _p = self._tts_priority(name)
                QTimer.singleShot(8000, lambda t=tts_text, p=_p: self.tts.speak(t, priority=p))
            else:
                self.tts.speak(tts_text, priority=self._tts_priority(name))

        if name == "FSDJump" and isinstance(incoming_system_address, int) and incoming_system_address != old_system_address:
            QTimer.singleShot(8000, self._announce_loaded_system_bodies)
            farm_brief = self._farming_arrival_brief(self.state)
            if farm_brief:
                QTimer.singleShot(13500, lambda t=farm_brief: self.tts.speak(t, priority=5))

        if name == "ReceiveText":
            self._handle_comms_tts(evt)

        if name in ("ReceiveText", "ShipTargeted"):
            self._handle_combat_quip(name, evt)

        if name == "ShipTargeted" and int(evt.get("ScanStage", 0) or 0) >= 3:
            self._refresh_combat()

    def _farming_arrival_brief(self, state) -> str:
        """Short TTS summary of farming opportunities on FSDJump. Returns '' if nothing relevant."""
        try:
            if not self.farming_locations:
                return ""

            sys_name = getattr(state, "system", None) or ""
            parts = []

            # ── Exact system name match ───────────────────────────────────
            exact = self.farming_locations.get_for_system(sys_name) if sys_name else []
            if exact:
                names = [str(r.get("name") or "") for r in exact if r.get("name")]
                if names:
                    parts.append(f"Known farming site: {names[0]}.")

            # ── Faction state tags ────────────────────────────────────────
            govt = str(getattr(state, "system_government", "") or "").lower()
            faction_tags = set()
            for f in (getattr(state, "factions", None) or []):
                if not isinstance(f, dict):
                    continue
                all_states = [str(f.get("FactionState") or "").lower()]
                for st in (f.get("ActiveStates") or []):
                    if isinstance(st, dict):
                        all_states.append(str(st.get("State") or "").lower())
                for s in all_states:
                    if "boom" in s:
                        faction_tags.add("boom")
                    if "war" in s:
                        faction_tags.add("war")
                    if "outbreak" in s:
                        faction_tags.add("outbreak")
                    if "pirate" in s and "attack" in s:
                        faction_tags.add("pirate_attack")
                    if "civil unrest" in s:
                        faction_tags.add("civil_unrest")

            tag_parts = []
            if "boom" in faction_tags:
                tag_parts.append("HGE active")
            if "war" in faction_tags:
                tag_parts.append("Combat Zones active")
            if "outbreak" in faction_tags:
                tag_parts.append("HGE outbreak")
            if "pirate_attack" in faction_tags:
                tag_parts.append("Pirate Attack settlements")
            if "civil_unrest" in faction_tags:
                tag_parts.append("Civil Unrest")
            if "anarchy" in govt:
                tag_parts.append("Anarchy — high wake scans available")

            if tag_parts:
                parts.append(". ".join(tag_parts) + ".")

            return " ".join(parts) if parts else ""
        except Exception:
            return ""

    def _tts_router(self, event_type: str, evt: dict, state) -> str:
        """Route journal events to TTS phrase generators."""
        try:
            enabled = getattr(self.cfg, "tts_enabled", False)
            if not enabled:
                log.debug(f"TTS disabled")
                return ""
            events = getattr(self.cfg, "tts_events", {}) or {}
            if not events.get(event_type, False):
                return ""
            log.debug(f"TTS routing: {event_type}")

            pledged = (getattr(state, "pp_power", None) or "").strip()

            if event_type == "StartJump":
                if evt.get("JumpType") == "Hyperspace":
                    parts = [ExplorationPhrases.fsd_announce()]
                    jumps = getattr(state, "route_remaining_jumps", None)
                    if isinstance(jumps, int) and jumps == 1:
                        parts.append("Last jump.")
                    elif isinstance(jumps, int) and jumps == 2:
                        parts.append("1 jump remaining.")
                    elif isinstance(jumps, int) and jumps > 2:
                        parts.append(f"{jumps - 1} jumps remaining.")
                    star_class = str(evt.get("StarClass") or "").strip().upper()
                    if star_class:
                        if star_class[0] in ("K", "G", "B", "F", "O", "A", "M"):
                            parts.append("Next Start is Scoopable.")
                        else:
                            parts.append("Next Start is Not scoopable.")
                    return " ".join(parts)
                return ""

            if event_type == "Location":
                system = getattr(state, "system", None) or ""
                if not system:
                    return ""
                ctrl = (getattr(state, "system_controlling_power", None) or "").strip()
                pp_state = getattr(state, "system_powerplay_state", None) or ""
                if pledged:
                    if ctrl:
                        return PowerPlayPhrases.pp_space(ctrl, pp_state, pledged)
                    system_powers = [p.strip() for p in (getattr(state, "system_powers", []) or [])]
                    if any(p.lower() == pledged.lower() for p in system_powers):
                        return PowerPlayPhrases.pp_present(pledged)
                return ExplorationPhrases.in_system(system)

            if event_type == "FSDJump":
                system = getattr(state, "system", None) or ""
                if not system:
                    return ""
                ctrl          = (getattr(state, "system_controlling_power", None) or "").strip()
                pp_state      = getattr(state, "system_powerplay_state", None) or ""
                security      = (getattr(state, "system_security", None) or "").strip()
                system_powers = [p.strip() for p in (getattr(state, "system_powers", []) or [])]
                if pledged:
                    if ctrl or pp_state:
                        base = PowerPlayPhrases.pp_space(ctrl, pp_state, pledged)
                    elif any(p.lower() == pledged.lower() for p in system_powers):
                        base = PowerPlayPhrases.pp_present(pledged)
                    else:
                        base = ExplorationPhrases.arrived()
                else:
                    base = ExplorationPhrases.arrived()
                if security:
                    return f"{base} {ExplorationPhrases.security_state(security)}"
                return base

            if event_type == "LoadGame":
                cmdr = getattr(state, "commander", None) or evt.get("Commander") or ""
                ship = evt.get("Ship_Localised") or getattr(state, "ship", None) or ""
                if cmdr:
                    return StatusPhrases.game_loaded(cmdr, ship)

            if event_type == "ScanOrganic":
                stage   = evt.get("ScanType") or ""
                species = evt.get("Species_Localised") or evt.get("Species") or ""
                if stage.lower() == "sample" and species:
                    body_id  = evt.get("Body")
                    evt_sp   = species.strip().lower()
                    for rec in (state.exo or {}).values():
                        if not isinstance(rec, dict):
                            continue
                        if rec.get("BodyID") != body_id:
                            continue
                        rec_sp = (rec.get("Species") or "").strip().lower()
                        if rec_sp and (rec_sp == evt_sp or rec_sp in evt_sp or evt_sp in rec_sp):
                            if int(rec.get("Samples") or 2) >= 3:
                                stage = "SampleFinal"
                            break
                if stage and species:
                    return ExobiologyPhrases.scan_progress(stage, species)

            if event_type == "SellOrganicData":
                reward = evt.get("TotalEarnings") or 0
                bios   = evt.get("BioData") or []
                count  = len(bios) if isinstance(bios, list) else 0
                if reward:
                    return ExobiologyPhrases.sell_data(reward, count)

            if event_type == "Scan":
                body_name = evt.get("BodyName") or ""
                if not body_name:
                    return ""
                rec = (getattr(state, "bodies", {}) or {}).get(body_name)
                if not rec:
                    return ""  # star or untracked body
                first_discovered = bool(rec.get("FirstDiscovered"))
                if first_discovered:
                    return ExplorationPhrases.first_discovery(body_name)
                return ""

            if event_type == "FSSSignalDiscovered":
                uss_type = evt.get("USSType") or ""
                if uss_type == "$USS_Type_NonHuman;":
                    threat = evt.get("ThreatLevel")
                    if isinstance(threat, int):
                        return ExplorationPhrases.nhss_detected(threat)

                sig_type = (evt.get("SignalType") or "").strip().lower()
                if sig_type == "megaship":
                    signal_name = evt.get("SignalName") or ""
                    mega_key = MegashipTracker.key(evt.get("SystemAddress"), signal_name)
                    if signal_name and not self.megaship_tracker.has_seen(mega_key):
                        pledged = (getattr(state, "pp_power", None) or "").strip()
                        ctrl = (getattr(state, "system_controlling_power", None) or "").strip()
                        pp_state_val = (getattr(state, "system_powerplay_state", None) or "").strip()
                        if pledged:
                            # Marking "done" happens on confirmed drop-in
                            # (SupercruiseDestinationDrop), not here — this
                            # only decides whether it's worth alerting about.
                            # Reinforcement: our own power controls this system
                            if ctrl and ctrl.lower() == pledged.lower():
                                return ExplorationPhrases.megaship_pp_merits("reinforcement")
                            # Acquisition: no controlling power, but PP-active
                            if not ctrl and pp_state_val:
                                return ExplorationPhrases.megaship_pp_merits("acquisition")
                return ""

            if event_type == "USSDrop":
                if evt.get("USSType") == "$USS_Type_NonHuman;":
                    threat = evt.get("USSThreat")
                    if isinstance(threat, int):
                        return ExplorationPhrases.nhss_detected(threat)
                return ""

            if event_type == "SAAScanComplete":
                body = evt.get("BodyName") or ""
                was_mapped = bool(evt.get("WasMapped", True))
                if not was_mapped:
                    return ExplorationPhrases.first_mapped(body)
                return ExplorationPhrases.saa_complete(body)

            if event_type == "Disembark":
                if not bool(evt.get("OnPlanet", False)):
                    return ""
                if not bool(evt.get("FirstFootfall", False)):
                    return ""
                body = evt.get("Body") or evt.get("BodyName") or ""
                return ExplorationPhrases.first_footfall(body)

            if event_type == "UnderAttack":
                return CombatPhrases.under_attack()

            if event_type == "ShipTargeted":
                if not evt.get("TargetLocked"):
                    return ""
                if int(evt.get("ScanStage", 0) or 0) < 3:
                    return ""

                rank         = str(evt.get("PilotRank") or "").strip()
                legal_status = str(evt.get("LegalStatus") or "").strip()
                wanted       = legal_status.lower() == "wanted"
                bounty       = int(evt.get("Bounty") or 0)
                power        = (evt.get("Power") or "").strip()
                faction      = (evt.get("Faction") or "").strip().lower()
                is_friendly  = bool(pledged and power and power.lower() == pledged.lower())
                top_rank     = rank.lower() in ("dangerous", "deadly", "elite")

                # Never call out law enforcement or our own power's ships
                if "internal security" in faction or "security service" in faction:
                    return ""
                if is_friendly:
                    return ""

                ctrl          = (getattr(state, "system_controlling_power", None) or "").strip()
                system_powers = [p.strip() for p in (getattr(state, "system_powers", []) or [])]
                we_control    = bool(pledged and ctrl and ctrl.lower() == pledged.lower())
                we_present    = bool(pledged and any(p.lower() == pledged.lower() for p in system_powers))
                we_active     = we_control or we_present

                power_lower = power.lower() if power else ""
                ship_in_ctrl   = bool(ctrl and power_lower and power_lower == ctrl.lower())
                ship_in_powers = bool(power and any(p.lower() == power_lower for p in system_powers))
                ship_active    = ship_in_ctrl or ship_in_powers

                if we_active and power and ship_active:
                    is_enemy = True
                    is_high_value = False
                elif wanted and bounty > 500_000 and top_rank:
                    is_enemy = False
                    is_high_value = True
                else:
                    return ""

                pilot = evt.get("PilotName_Localised") or evt.get("PilotName") or ""
                ship  = evt.get("Ship_Localised") or evt.get("Ship") or ""
                key   = f"{pilot}|{ship}"
                if key in self._tts_spoken_ships:
                    return ""
                self._tts_spoken_ships.add(key)

                now = time.monotonic()
                if now < self._tts_ship_cooldown_until:
                    return ""
                self._tts_ship_cooldown_until = now + 6.0
                return CombatPhrases.ship_targeted(
                    ship, rank, power, is_enemy, wanted, bounty, is_high_value
                )

            if event_type == "FSSBodySignals":
                body = evt.get("BodyName") or ""
                if body in self._tts_spoken_signal_bodies:
                    return ""
                self._tts_spoken_signal_bodies.add(body)
                thargoid = (getattr(state, "thargoid_signals", {}) or {}).get(body, 0)
                if thargoid > 0:
                    return ExplorationPhrases.thargoid_signals(body, thargoid)
                guardian = (getattr(state, "guardian_signals", {}) or {}).get(body, 0)
                if guardian > 0:
                    return ExplorationPhrases.guardian_signals(body, guardian)
                bio = (getattr(state, "bio_signals", {}) or {}).get(body, 0)
                if bio > 0:
                    return ExplorationPhrases.bio_signals(body, bio)
                geo = (getattr(state, "geo_signals", {}) or {}).get(body, 0)
                if geo > 0:
                    return ExplorationPhrases.geo_signals(body, geo)
                human = (getattr(state, "human_signals", {}) or {}).get(body, 0)
                if human > 0:
                    return ExplorationPhrases.human_signals(body, human)

            if event_type == "FSSAllBodiesFound":
                # The game can genuinely emit this more than once for the
                # same system (e.g. multi-star systems re-confirming
                # completeness as distant bodies resolve) — announce once
                # per system, not once per event.
                system_address = evt.get("SystemAddress") or getattr(state, "system_address", None)
                if isinstance(system_address, int):
                    if system_address in self._tts_fss_complete_systems:
                        return ""
                    self._tts_fss_complete_systems.add(system_address)
                count = int(evt.get("Count") or evt.get("BodyCount") or getattr(state, "system_body_count", None) or 0)
                if count:
                    return ExplorationPhrases.fss_complete(count)

            if event_type == "Bounty":
                reward  = evt.get("TotalReward") or evt.get("Reward") or 0
                faction = evt.get("VictimFaction") or ""
                if reward:
                    return CombatPhrases.bounty(reward, faction)

            if event_type == "FactionKillBond":
                reward  = evt.get("Reward") or 0
                faction = evt.get("AwardingFaction") or ""
                if reward:
                    return CombatPhrases.kill_bond(reward, faction)

            if event_type == "Interdicted":
                return CombatPhrases.interdiction()

            if event_type == "EscapeInterdiction":
                return CombatPhrases.escape_interdiction()

            if event_type == "Scanned":
                scan_type = str(evt.get("ScanType") or "").capitalize()
                return StatusPhrases.scan_complete(scan_type)

            if event_type == "CodexEntry":
                if evt.get("IsNewEntry"):
                    name = evt.get("Name_Localised") or evt.get("Name") or ""
                    return ExplorationPhrases.codex_entry(name)

            if event_type == "MissionCompleted":
                reward  = evt.get("Reward") or 0
                faction = evt.get("Faction") or ""
                if reward:
                    return StatusPhrases.mission_complete(reward, faction)

        except Exception:
            pass
        return ""

    # Kept in sync with the sidebar order set up in __init__ (Overview
    # pinned first, then Combat, Engineering, Exobiology, Exploration,
    # Fleet Carrier, Intel, Market, Materials, Mining, Odyssey, Player
    # Faction, PowerPlay, Squadron, Voice Cmds, then Settings/Log pinned
    # last). Voice Cmds/Settings/Log deliberately have no voice trigger.
    _TAB_INDEX: dict = {
        "Overview":       0,
        "Combat":         1,
        "Engineering":    2,
        "Exobiology":     3,
        "Exploration":    4,
        "Fleet Carrier":  5,
        "Intel":          6,
        "Market":         7,
        "Materials":      8,
        "Mining":         9,
        "Odyssey":        10,
        "Player Faction": 11,
        "PowerPlay":      12,
        "Squadron":       13,
    }

    def _start_voice_commands(self):
        if self._voice_cmd_thread and self._voice_cmd_thread.isRunning():
            return
        self._voice_cmd_worker = VoiceCommandListener(self._voice_cmd_models_dir)
        # Push current ship commands into the listener before starting
        self._sync_ship_commands_to_listener()
        self._voice_cmd_thread = QThread()
        self._voice_cmd_worker.moveToThread(self._voice_cmd_thread)
        self._voice_cmd_thread.started.connect(self._voice_cmd_worker.run)
        self._voice_cmd_worker.command_detected.connect(self._on_voice_command)
        self._voice_cmd_worker.ship_command_detected.connect(self._on_ship_voice_command)
        self._voice_cmd_worker.listener_ready.connect(self._on_voice_listener_ready)
        self._voice_cmd_worker.trigger_heard.connect(self._on_voice_trigger_heard)
        self._voice_cmd_worker.command_unrecognised.connect(self._on_voice_unrecognised)
        self._voice_cmd_thread.start()
        log.info("Voice commands started")

    def _sync_ship_commands_to_listener(self):
        if not self._voice_cmd_worker:
            return
        cmds    = self.voice_commands_panel.active_commands()
        trigger = self.voice_commands_panel.trigger_word()
        self._voice_cmd_worker.update_ship_commands(cmds, trigger)
        self._voice_cmd_worker.set_nav_trigger_word(self.voice_commands_panel.nav_trigger_word())
        self._voice_cmd_worker.set_input_device(self.voice_commands_panel.input_device())

    def _on_voice_commands_config_changed(self):
        """Called when the user edits the Voice Commands panel."""
        new_device = self.voice_commands_panel.input_device()
        mic_changed = (
            self._voice_cmd_worker is not None
            and getattr(self._voice_cmd_worker, "_input_device_name", None) != new_device
        )
        self._sync_ship_commands_to_listener()
        if mic_changed and self.cfg.voice_commands_enabled:
            log.info("Microphone selection changed — restarting voice commands")
            self._stop_voice_commands()
            self._start_voice_commands()
        self.tts.set_output_device(self.voice_commands_panel.output_device())

    def _stop_voice_commands(self):
        if self._voice_cmd_worker:
            self._voice_cmd_worker.stop()
        if self._voice_cmd_thread:
            self._voice_cmd_thread.quit()
            self._voice_cmd_thread.wait(2000)
        self._voice_cmd_worker = None
        self._voice_cmd_thread = None
        log.info("Voice commands stopped")

    def _populate_voice_combo(self):
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for _, vname in self.tts.get_available_voices():
            self.voice_combo.addItem(vname)
        self.voice_combo.setCurrentIndex(int(getattr(self.cfg, "tts_voice_index", 0)))
        self.voice_combo.blockSignals(False)

    def _on_eddn_contribute_toggled(self, checked: bool):
        self.cfg.eddn_contribute_enabled = bool(checked)
        self.cfg_store.save(self.cfg)

    def _on_market_radius_changed(self, value: int):
        self.cfg.market_search_radius_ly = int(value)
        self.cfg_store.save(self.cfg)

    def _on_always_on_top_changed(self, checked: bool):
        self.cfg.always_on_top = bool(checked)
        self.cfg_store.save(self.cfg)
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def _on_voice_commands_toggled(self, checked: bool):
        self.cfg.voice_commands_enabled = checked
        self.cfg_store.save(self.cfg)
        if checked:
            self._start_voice_commands()
        else:
            self._stop_voice_commands()

    def _feedback_volume(self) -> float:
        """Voice-command feedback volume from the Voice Cmds panel slider —
        independent of the main voice and comms volumes."""
        try:
            return float(self.voice_commands_panel.feedback_volume())
        except Exception:
            return 0.5

    def _feedback_tts_scale(self) -> float:
        """Scale factor so feedback phrases play at the feedback volume
        regardless of the main voice volume the TTS engine applies."""
        main_vol = float(getattr(self.cfg, "tts_volume", 0.6))
        if main_vol <= 0:
            return 0.0
        return self._feedback_volume() / main_vol

    def _play_radio_click(self, end: bool = False):
        """Play a PTT-style radio click as the voice-command cue tone.
        Replaces a pure sine-tone beep that read as sharp/piercing through
        headphones even with a fade envelope — winsound.Beep was avoided
        for the same reason (raw square wave, ignores volume control) but
        the tone itself was still the problem.

        Not the shared NPC-comms click (edc/audio/_comms_edge_proc.py):
        that one is deliberately mid-band-only (600-2400Hz) and held to 70%
        headroom so it doesn't compete with the TTS line that follows it
        there — both of those made it read as thin/papery as a standalone
        cue with nothing else playing. This version widens the band down
        into the low-mids and layers in a short decaying low-frequency
        "thump" for actual body, at full configured volume.

        end=True uses a close-click (with a brief static tail) for
        "didn't understand"/"can't do that" cues; end=False (open click,
        just a punch) for "trigger heard, listening now"."""
        def _worker():
            try:
                import numpy as np
                import miniaudio
                import threading as _threading
                from scipy.signal import butter, sosfilt
                from edc.audio.audio_devices import resolve_playback_device_id

                sr  = 22050
                vol = self._feedback_volume()

                n = int(sr * 0.045)
                t = np.linspace(0, 1, n, endpoint=False)
                env = np.exp(-t * 70.0) * (1.0 - np.exp(-t * 700.0))
                click = np.random.normal(0, 1.0, n).astype("float32") * env.astype("float32")
                sos = butter(4, [150, 3000], btype="band", fs=sr, output="sos")
                click = sosfilt(sos, click).astype("float32")

                # Low-frequency punch layered under the click's front edge —
                # this is what was missing: the band-passed noise alone has
                # snap but no weight.
                punch_n = int(sr * 0.025)
                pt = np.arange(punch_n) / sr
                punch_env = np.exp(-pt * 140.0)
                punch = (np.sin(2 * np.pi * 110.0 * pt) * punch_env).astype("float32")
                click[:punch_n] += punch * 0.9

                click = np.tanh(click * 4.0).astype("float32")
                peak = float(np.max(np.abs(click)))
                if peak > 0:
                    click = click / peak * float(vol)

                if end:
                    n_tail = int(sr * 0.08)
                    t_tail = np.linspace(0, 1, n_tail, endpoint=False)
                    tail_env = np.exp(-t_tail * 6.0)
                    tail = np.random.normal(0, 1.0, n_tail).astype("float32") * tail_env.astype("float32")
                    sos2 = butter(3, [300, 3000], btype="band", fs=sr, output="sos")
                    tail = sosfilt(sos2, tail).astype("float32") * float(vol) * 0.28
                    click = np.concatenate([click, tail])

                pcm = (np.clip(click, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

                done = _threading.Event()

                def _gen():
                    pos = 0
                    try:
                        num_frames = yield b""
                        while pos < len(pcm):
                            chunk = pcm[pos:pos + num_frames * 2]
                            pos += num_frames * 2
                            num_frames = yield chunk
                    except Exception:
                        pass
                    finally:
                        done.set()

                device = miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=1,
                    sample_rate=sr,
                    buffersize_msec=40,
                    device_id=resolve_playback_device_id(
                        self.voice_commands_panel.output_device()),
                )
                gen = _gen()
                next(gen)
                device.start(gen)
                try:
                    done.wait(timeout=len(click) / sr + 0.5)
                finally:
                    device.stop()
            except Exception:
                log.exception("_play_radio_click failed")

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _on_voice_listener_ready(self):
        self._voice_ready = True
        self._maybe_announce_online()

    def notify_startup_complete(self):
        """Called from app.py once the launch sequence has run (splash closed,
        window shown, data load and watchers kicked off)."""
        self._startup_complete = True
        self._maybe_announce_online()

    def _maybe_announce_online(self):
        """Speak the one-time startup cue only when everything is actually up.
        Spoken via TTS rather than winsound.Beep: Beep is a raw system tone that
        ignores volume settings entirely, which made startup jarringly loud.
        Half the main voice volume so startup stays unobtrusive."""
        if self._online_announced or not self._startup_complete:
            return
        voice_enabled = bool(getattr(self.cfg, "voice_commands_enabled", False))
        if voice_enabled and not self._voice_ready:
            return
        self._online_announced = True
        self.tts.speak("All systems online.", priority=5, volume_scale=self._feedback_tts_scale())

    def _start_app_shutdown_countdown(self):
        if self._shutdown_countdown_timer is not None:
            return  # already counting down
        log.info(
            "Elite Dangerous closed — app will follow in %ds unless it restarts",
            self._APP_SHUTDOWN_DELAY_S,
        )
        self._shutdown_countdown_timer = QTimer(self)
        self._shutdown_countdown_timer.setSingleShot(True)
        self._shutdown_countdown_timer.timeout.connect(self._say_goodbye_and_close)
        self._shutdown_countdown_timer.start(self._APP_SHUTDOWN_DELAY_S * 1000)

    def _cancel_app_shutdown_countdown(self):
        if self._shutdown_countdown_timer is None:
            return
        log.info("Elite Dangerous appears active again — cancelling app shutdown countdown")
        self._shutdown_countdown_timer.stop()
        self._shutdown_countdown_timer = None

    def _say_goodbye_and_close(self):
        self._shutdown_countdown_timer = None
        self.tts.speak(
            "Elite Dangerous has closed. Goodbye, Commander — fly safe.",
            priority=5, volume_scale=self._feedback_tts_scale(),
        )
        # Give the phrase time to actually play before the app (and its
        # audio device) tears down.
        QTimer.singleShot(6000, self.close)

    def _on_voice_trigger_heard(self):
        """Trigger word heard. No audio cue — removed per user request: the
        click read as too sharp, and since trigger detection also fires on
        Vosk *partial* results (accepted early for responsiveness, not just
        the more reliable final result), it could play on a brief mis-hear
        of background/game audio as the trigger word, not just a real one."""
        pass

    def _on_voice_unrecognised(self):
        """Trigger word was heard but the phrase matched nothing — closing
        click (with static tail) so the user knows to just retry instead of
        wondering if the system hung."""
        self._play_radio_click(end=True)

    def _on_voice_command(self, tab_name: str):
        idx = self._TAB_INDEX.get(tab_name)
        if idx is None:
            return
        self.sidebar.setCurrentRow(idx)

    def _on_ship_voice_command(self, phrase: str):
        """Dispatch a recognised ship voice command via pydirectinput."""
        from edc.core.ship_command_dispatcher import game_window_focused
        if not game_window_focused():
            # Keystrokes land in whatever window has focus — sending them while
            # the game isn't foreground would type into our own UI (arrow keys
            # move the sidebar = "menu changed by itself") or another app.
            log.info("Ship command '%s' skipped — Elite Dangerous is not the focused window", phrase)
            self._play_radio_click(end=True)
            return
        cmds = self.voice_commands_panel.active_commands()
        for cmd in cmds:
            if cmd.get("phrase", "").lower() == phrase.lower():
                binding = cmd.get("_binding")
                repeat  = int(cmd.get("repeat", 1))
                if binding:
                    import threading
                    threading.Thread(
                        target=self._ship_dispatcher.dispatch,
                        args=(binding, repeat),
                        daemon=True,
                    ).start()
                    log.info("Ship command fired: '%s' → %s (×%d)", phrase, cmd.get("action"), repeat)
                    confirm = cmd.get("confirm", "").strip()
                    if confirm:
                        self.tts.speak(confirm, priority=3, volume_scale=self._feedback_tts_scale())
                return

    def _on_tts_enabled_changed(self, checked: bool):
        try:
            self.cfg.tts_enabled = bool(checked)
            self.tts.load_from_config(self.cfg)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass

    def _on_main_voice_changed(self, idx: int):
        try:
            self.cfg.tts_voice_index = idx
            self.cfg_store.save(self.cfg)
        except Exception:
            pass

    def _test_main_voice(self):
        idx = self.voice_combo.currentIndex()
        self.tts.speak_test("Main voice active. How do I sound, Commander?", idx)

    def _on_tts_volume_changed(self, val: int):
        try:
            self.tts_vol_label.setText(f"{val}%")
            self.cfg.tts_volume = val / 100.0
            self.tts.load_from_config(self.cfg)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass

    def _on_comms_volume_changed(self, val: int):
        try:
            self.comms_vol_label.setText(f"{val}%")
            self.cfg.comms_volume = val / 100.0
            self.tts.load_from_config(self.cfg)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass

    def _on_comms_enabled_changed(self, checked: bool):
        try:
            self.cfg.comms_enabled = bool(checked)
            self.tts.load_from_config(self.cfg)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass

    def _handle_combat_quip(self, event_type: str, evt: dict):
        if not getattr(self.cfg, "tts_enabled", False):
            return
        now = time.monotonic()
        if now < self._commander_quip_cooldown_until:
            return

        pledged = (getattr(self.state, "pp_power", None) or "").strip()
        ctrl    = (getattr(self.state, "system_controlling_power", None) or "").strip()
        in_my_pp_space = bool(pledged and ctrl and ctrl == pledged)

        def _qualifies(power: str, wanted: bool, bounty, rank: str) -> bool:
            rank_ok      = rank.lower() in ("dangerous", "deadly", "elite")
            bounty_ok    = isinstance(bounty, int) and bounty >= 500_000
            bounty_target = wanted and bounty_ok and rank_ok
            pp_enemy      = bool(pledged and power and power != pledged)
            if in_my_pp_space:
                return pp_enemy or bounty_target
            return bounty_target

        quip = ""
        if event_type == "ReceiveText":
            from_raw = evt.get("From") or ""
            if "$npc_name_decorate" not in from_raw:
                return
            # Parse pilot name from "$npc_name_decorate:#name=X;"
            pilot_name = ""
            if "#name=" in from_raw:
                pilot_name = from_raw.split("#name=", 1)[1].rstrip(";").strip()
            if not pilot_name:
                return
            contacts = getattr(self.state, "combat_contacts", {}) or {}
            contact = next(
                (c for c in contacts.values()
                 if isinstance(c, dict) and c.get("Pilot") == pilot_name),
                None,
            )
            if not contact:
                return
            if _qualifies(contact.get("Power", ""), contact.get("Wanted", False),
                          contact.get("Bounty"), contact.get("Rank", "")):
                quip = CombatPhrases.npc_challenge()
        elif event_type == "ShipTargeted":
            if not evt.get("TargetLocked") or int(evt.get("ScanStage", 0) or 0) < 3:
                return
            power  = (evt.get("Power") or "").strip()
            legal  = str(evt.get("LegalStatus") or "").strip().lower()
            wanted = legal == "wanted"
            bounty = evt.get("Bounty")
            rank   = str(evt.get("PilotRank") or "").strip()
            if _qualifies(power, wanted, bounty, rank):
                quip = CombatPhrases.wanted_target_scan()

        if not quip:
            return
        self._commander_quip_cooldown_until = now + 30.0
        if event_type == "ReceiveText":
            QTimer.singleShot(2000, lambda q=quip: self.tts.speak(q, priority=3))
        else:
            self.tts.speak(quip, priority=3)

    def _handle_comms_tts(self, evt: dict):
        if not getattr(self.cfg, "comms_enabled", False):
            return
        channel = evt.get("Channel") or ""
        if channel in ("squadron", "wing", "squadronleader"):
            msg = (evt.get("Message_Localised") or evt.get("Message") or "").strip()
            if not msg or msg.startswith("$"):
                return
            from_name = evt.get("From_Localised") or evt.get("From") or "Squadron"
            label = "Wing" if channel == "wing" else "Squadron"
            self.tts.speak_squadron(f"{label}, {from_name}: {msg}")
            return
        if channel == "player":
            # Direct/private tell — notify only, don't read the content out
            # (unlike squadron/local chatter, a private message may not be
            # meant for whoever's in earshot).
            msg = (evt.get("Message_Localised") or evt.get("Message") or "").strip()
            if not msg or msg.startswith("$"):
                return
            from_name = evt.get("From_Localised") or evt.get("From") or "a commander"
            self.tts.speak(f"Commander, private message from {from_name}.", priority=6)
            return
        if channel in ("friend", "direct", "voicechat"):
            return
        msg = (evt.get("Message_Localised") or evt.get("Message") or "").strip()
        if not msg or msg.startswith("$"):
            return
        self.tts.speak_comms(msg)

    def _announce_loaded_system_bodies(self):
        if not getattr(self.cfg, "tts_enabled", False):
            return
        events = getattr(self.cfg, "tts_events", {}) or {}
        bodies = getattr(self.state, "bodies", {}) or {}
        if not bodies:
            return

        if events.get("Scan", False):
            threshold = int(getattr(self.cfg, "min_planet_value_100k", 5) or 5) * 100_000
            hv_count = sum(
                1 for rec in bodies.values()
                if isinstance(rec, dict)
                and isinstance(rec.get("EstimatedValue"), int)
                and rec["EstimatedValue"] >= threshold
                and not rec.get("DSSMapped", False)
            )
            if hv_count > 0:
                self.tts.speak(ExplorationPhrases.valuable_bodies_summary(hv_count), priority=5)

        if events.get("FSSBodySignals", False):
            bio_signals   = getattr(self.state, "bio_signals",   {}) or {}
            geo_signals   = getattr(self.state, "geo_signals",   {}) or {}
            human_signals = getattr(self.state, "human_signals", {}) or {}
            bio_bodies   = sum(1 for v in bio_signals.values()   if int(v or 0) > 0)
            geo_bodies   = sum(1 for v in geo_signals.values()   if int(v or 0) > 0)
            human_bodies = sum(1 for v in human_signals.values() if int(v or 0) > 0)
            if bio_bodies or geo_bodies or human_bodies:
                self.tts.speak(
                    ExplorationPhrases.signals_summary(bio_bodies, geo_bodies, human_bodies),
                    priority=5
                )
                # Mark all signal bodies as announced so FSSBodySignals doesn't repeat them
                for body in bio_signals:
                    if int(bio_signals.get(body) or 0) > 0:
                        self._tts_spoken_signal_bodies.add(body)
                for body in geo_signals:
                    if int(geo_signals.get(body) or 0) > 0:
                        self._tts_spoken_signal_bodies.add(body)
                for body in human_signals:
                    if int(human_signals.get(body) or 0) > 0:
                        self._tts_spoken_signal_bodies.add(body)

    def _tts_priority(self, event_type: str) -> int:
        """Lower number = higher urgency."""
        PRIORITIES = {
            "Interdicted":        1,
            "EscapeInterdiction": 1,
            "UnderAttack":        1,
            "ShipTargeted":       2,
            "Scanned":            2,
            "Scan":               3,
            "ScanOrganic":        3,
            "SellOrganicData":    3,
            "StartJump":          4,
            "FSDJump":            4,
            "Location":           4,
            "LoadGame":           4,
            "SAASignalsFound":    5,
            "FSSBodySignals":     5,
            "FSSSignalDiscovered": 5,
            "SAAScanComplete":    6,
            "Disembark":          3,
            "FSSAllBodiesFound":  6,
            "Bounty":             6,
            "FactionKillBond":    6,
            "CodexEntry":         8,
            "MissionCompleted":   8,
        }
        return PRIORITIES.get(event_type, 5)

    def _schedule_hud_refresh(self):
        """Coalesce multiple rapid journal events into a single UI refresh."""
        try:
            if self._hud_refresh_pending:
                return
            self._hud_refresh_pending = True

            # 75ms feels "live" but avoids thrashing during FSS/DSS bursts.
            self._hud_refresh_timer.start(75)
        except Exception:
            # Worst case: fall back to immediate refresh
            self._hud_refresh_pending = False
            try:
                self._refresh_hud()
            except Exception:
                log.exception("UI refresh error (fallback)")

    def _do_hud_refresh(self):
        """Timer callback for the debounced HUD refresh."""
        self._hud_refresh_pending = False
        try:
            self._refresh_hud()
        except Exception:
            log.exception("UI refresh error")

    def _derive_pp_action(self, pledged, ctrl, pp_state, powers):
        return self.powerplay_panel.derive_pp_action(
            pledged, ctrl, pp_state, powers
        )

    def _format_poi_line(self, poi: Dict[str, Any]) -> str:
        """One-line, low-noise POI formatting for HUD."""
        try:
            title = fmt.text(poi.get("title") or "POI", default="POI")
            body = fmt.text(poi.get("body") or "", default="")
            note = fmt.text(poi.get("note") or "", default="")
            cat = fmt.text(poi.get("category") or "", default="")
            bits = []
            if cat:
                bits.append(cat)
            bits.append(title)
            if body:
                bits.append(f"@ {body}")
            line = " — ".join([" ".join(bits[:2]).strip(), " ".join(bits[2:]).strip()]).strip(" —")
            if note:
                line = f"{line} — {note}"
            return line.strip()
        except Exception:
            return ""

    def _format_farm_line(self, farm: Dict[str, Any]) -> str:
        """One-line, low-noise farming formatting for HUD."""
        try:
            name = fmt.text(farm.get("name") or "Farming", default="Farming")
            body = fmt.text(farm.get("body") or "", default="")
            method = fmt.text(farm.get("method") or "", default="")
            mats = farm.get("key_materials") or farm.get("materials") or []
            mats_txt = ""
            if isinstance(mats, list):
                top = [fmt.text(x, default="") for x in mats][:2]
                top = [x for x in top if x]
                if top:
                    mats_txt = ", ".join(top)
            bits = [name]
            if body:
                bits.append(f"@ {body}")
            if method:
                bits.append(method)
            line = " — ".join([b for b in bits if b])
            if mats_txt:
                line = f"{line} (e.g. {mats_txt})"
            return line.strip()
        except Exception:
            return ""

    def _maybe_add_system_intel_hints(self, lines: List[str]) -> None:
        """Add POI/Farming hints once per system change (non-spammy)."""
        try:
            sys_name = fmt.text(getattr(self.state, "system", None), default="").strip()
            sys_addr = getattr(self.state, "system_address", None)
            addr_key = str(sys_addr) if isinstance(sys_addr, int) else ""
            if not sys_name:
                return

            system_key = f"{sys_name}|{addr_key}"
            if system_key == self._last_intel_system_key:
                return
            self._last_intel_system_key = system_key

            pois = self.external_intel.get_pois(sys_name, sys_addr if isinstance(sys_addr, int) else None) or []
            farms = self.farming_locations.get_for_system(sys_name) if sys_name else []

            poi_lines = []
            if isinstance(pois, list):
                for p in pois[:3]:
                    if isinstance(p, dict):
                        s = self._format_poi_line(p)
                        if s:
                            poi_lines.append(s)

            farm_lines = []
            if isinstance(farms, list):
                for f in farms[:2]:
                    if isinstance(f, dict):
                        s = self._format_farm_line(f)
                        if s:
                            farm_lines.append(s)

            if poi_lines:
                lines.append(f"📌 POI: {poi_lines[0]}")
                for extra in poi_lines[1:]:
                    lines.append(f"   ↳ {extra}")

            if farm_lines:
                lines.append(f"⛏️ Farming: {farm_lines[0]}")
                for extra in farm_lines[1:]:
                    lines.append(f"   ↳ {extra}")
        except Exception:
            log.exception("Failed to add system intel hints")

    def _refresh_hud(self):
        parts = []
        lines = []
        self._pp_action_text = ""
        action_state = self._compute_action_state()
        if (
            self.state.commander
            or self.state.ship
            or self.state.credits is not None
            or self.state.system
        ):
            parts.append(f"CMDR {self.state.commander or '?'}")
        if self.state.ship:
            parts.append(f"Ship: {self.state.ship}")
        if self.state.credits is not None:
            parts.append(f"Credits: {fmt.credits(self.state.credits, default='?')}")
        if self.state.system:
            if getattr(self.state, "in_hyperspace", False):
                sc = getattr(self.state, "jump_star_class", None)
                if sc:
                    parts.append(f"Jumping to: {self.state.system} ({sc})")
                else:
                    parts.append(f"Jumping to: {self.state.system}")
            else:
                parts.append(f"System: {self.state.system}")

        if self.state.pp_power:
            # Keep it compact
            pr = self.state.pp_rank if self.state.pp_rank is not None else "?"
            me = self.state.pp_merits if self.state.pp_merits is not None else "?"
            parts.append(f"PP: {self.state.pp_power} (R{pr} M{me})")
        if self.state.last_event:
            parts.append(f"Last: {self.state.last_event}")
        if parts:
            lines.append(" | ".join(parts))

        # PowerPlay: one-line "what can I do here?" hint (only if pledged and PP context exists)
        try:
            pledged = getattr(self.state, "pp_power", None)
            ctrl = getattr(self.state, "system_controlling_power", None)
            pp_state = getattr(self.state, "system_powerplay_state", None) or ""
            reinforce = getattr(self.state, "system_powerplay_reinforcement", None)
            undermine = getattr(self.state, "system_powerplay_undermining", None)
            progress = getattr(self.state, "system_powerplay_control_progress", None)
            powers = getattr(self.state, "system_powers", None) or []

            action = self._derive_pp_action(pledged, ctrl, pp_state, powers)
            if action:
                self._pp_action_text = f"PP Action: {action}"
        except Exception:
            pass

        # Ensure PowerPlay tab updates whenever HUD refreshes
        try:
            self._refresh_powerplay()
        except Exception:
            pass

        # ---- Update session tracker ----
        try:
            kills = getattr(self.state, "session_kills", 0)
            combat_session = int(getattr(self.state, "combat_session_collected", 0) or 0)
            combat_unsold = int(getattr(self.state, "combat_unsold_total", 0) or 0)

            exploration_session = int(getattr(self.state, "exploration_session_collected_est", 0) or 0)
            exploration_unsold = int(getattr(self.state, "exploration_unsold_total_est", 0) or 0)

            exo_session = int(getattr(self.state, "exobiology_session_collected_est", 0) or 0)
            exo_unsold = int(getattr(self.state, "exobiology_unsold_total_est", 0) or 0)

            pp_merits_session = int(
                getattr(self.state, "pp_merits_session", 0) or 0
            )
            pp_cell = f"<span style='color:#DDA0DD;'>PP Merits: +{pp_merits_session:,}</span>" if pp_merits_session > 0 else ""

            # Two-column grid instead of one tall stacked column — was pushing
            # everything below the header down by 8 lines' worth of height.
            self.session_panel.setText(
                "<table cellspacing='0' cellpadding='0' style='margin-top:2px;'>"
                f"<tr><td style='padding-right:14px;'>Session</td><td></td></tr>"
                f"<tr><td style='padding-right:14px;'>Kills: {kills}</td><td>{pp_cell}</td></tr>"
                f"<tr><td style='padding-right:14px;color:#FF8C66;'>Combat: {combat_session:,} cr</td>"
                f"<td style='color:#FFB199;'>Combat Unsold: {combat_unsold:,} cr</td></tr>"
                f"<tr><td style='padding-right:14px;color:#87CEFA;'>Exploration: {exploration_session:,} cr</td>"
                f"<td style='color:#B7E3FF;'>Expl. Unsold: {exploration_unsold:,} cr</td></tr>"
                f"<tr><td style='padding-right:14px;color:#7CFC98;'>Exobio: {exo_session:,} cr</td>"
                f"<td style='color:#BDFCC9;'>Exo Unsold: {exo_unsold:,} cr</td></tr>"
                "</table>"
            )

        except Exception:
            pass

        # ---- Update route tracker ----
        try:
            if not getattr(self.state, "in_hyperspace", False):
                route_target = getattr(self.state, "route_target_system", None)
                route_star_class = getattr(self.state, "route_target_star_class", None)
                route_jumps = getattr(self.state, "route_remaining_jumps", None)

                target_txt = route_target if isinstance(route_target, str) and route_target.strip() else "-"
                star_label, star_color = self._get_star_class_label_and_color(route_star_class)
                jumps_txt = str(route_jumps) if isinstance(route_jumps, int) else "-"

                if star_label:
                    next_line = (
                        f"Next: {target_txt} "
                        f"(<span style='color:{star_color};'>{star_label}</span>)"
                    )
                else:
                    next_line = f"Next: {target_txt}"

                self.route_panel.setText(
                    "Route<br>"
                    f"{next_line}<br>"
                    f"Jumps: {jumps_txt}"
                )
        except Exception:
            pass

        # PowerPlay status + action (ONLY if PP context exists in this system)
        try:
            pledged = self.state.pp_power
            ctrl = getattr(self.state, "system_controlling_power", None)
            pp_state = getattr(self.state, "system_powerplay_state", None)
            pw = getattr(self.state, "system_powers", None) or []
            prog = getattr(self.state, "system_powerplay_conflict_progress", None) or {}

            has_pp_context = bool(ctrl or pp_state or pw or prog)

            if pledged and has_pp_context:
                # --- Status line (HUD only) ---
                if ctrl == "Unoccupied":
                    ptxt = ", ".join([p for p in pw[:3] if isinstance(p, str)])
                    extra = f" | Powers: {ptxt}" if ptxt else ""
                    lines.append(f"🟡 PP: Neutral ({ctrl}) — {pp_state or 'Active'}{extra}")
                elif ctrl and ctrl == pledged:
                    lines.append(f"🟢 PP: Friendly space ({ctrl}) — {pp_state or 'Active'}")
                elif ctrl and ctrl != pledged:
                    lines.append(f"🔴 PP: Enemy-Controlled ({ctrl}) — {pp_state or 'Active'} (caution)")
                else:
                    ptxt = ", ".join([p for p in pw[:3] if isinstance(p, str)])
                    extra = f" | Powers: {ptxt}" if ptxt else ""
                    lines.append(f"🟡 PP: {pp_state or 'Active'}{extra}")

                # --- Action hint (Overview only) ---
                s = str(pp_state or "").lower()
                friendly = bool(ctrl and ctrl == pledged)
                enemy = bool(ctrl and ctrl != pledged and ctrl != "Unoccupied")

                action = None
                if "stronghold" in s or "fortified" in s:
                    if friendly:
                        action = "Fortify"
                    elif enemy:
                        action = "Enemy Stronghold"
                elif "contested" in s or "conflict" in s:
                    action = "Conflict ongoing"
                elif "unoccupied" in s:
                    if pledged in pw:
                        action = "Unoccupied"

                if action:
                    # Keep formatting consistent with the earlier PP action text.
                    if not self._pp_action_text:
                        self._pp_action_text = f"PP Action: {action}"
        except Exception:
            pass

        cgs = getattr(self.state, "community_goals", {}) or {}
        active = []
        for _cgid, rec in cgs.items():
            if not isinstance(rec, dict):
                continue
            if rec.get("IsComplete"):
                continue
            if rec.get("Title"):
                active.append(rec)
        if active:
            # Prefer the most recently joined CG if present
            prefer = getattr(self.state, "last_cg_joined", None)
            chosen = None
            if isinstance(prefer, int):
                chosen = cgs.get(prefer)
            if not isinstance(chosen, dict) or not chosen.get("Title") or chosen.get("IsComplete"):
                chosen = active[0]

            title = chosen.get("Title", "Community Goal")
            sysn = chosen.get("SystemName")
            mkt = chosen.get("MarketName")
            exp = chosen.get("Expiry")
            tier = chosen.get("TierReached")
            top = chosen.get("TopTierName")
            pc = chosen.get("PlayerContribution")

            loc = " — ".join([x for x in [sysn, mkt] if x])
            tier_txt = "/".join([x for x in [tier, top] if x])
            pc_txt = f"{pc:,}" if isinstance(pc, int) else "?"

            # Convert expiry timestamp to "Ends in Xd Yh"
            ends_txt = ""
            try:
                if isinstance(exp, str) and exp.endswith("Z"):
                    from datetime import datetime, timezone

                    expiry_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    remaining = expiry_dt - now

                    if remaining.total_seconds() > 0:
                        days = remaining.days
                        hours = int((remaining.seconds) / 3600)
                        if days > 0:
                            ends_txt = f"{days}d {hours}h"
                        else:
                            ends_txt = f"{hours}h"
            except Exception:
                ends_txt = ""

            percentile = chosen.get("PlayerPercentileBand")
            percentile_txt = f"Top {percentile}%" if isinstance(percentile, int) else ""
        
            bits = [f"CG: {title}"]
            if loc:
                bits.append(loc)
            bits.append(f"You {pc_txt}")
            if percentile_txt:
                bits.append(percentile_txt)
            if ends_txt:
                bits.append(f"Ends in {ends_txt}")
            lines.append(" | ".join(bits))

        # One-line "action hints" (what's worth doing in THIS system)
        try:
            min_100k = int(getattr(self.cfg, "min_planet_value_100k", 5) or 5)
        except Exception:
            min_100k = 5
        min_value = min_100k * 100_000
        fss_value = max(300_000, int(min_value * 0.20))

        try:
            exo_m = int(getattr(self.cfg, "exo_high_value_m", 2) or 2)
        except Exception:
            exo_m = 2
        exo_min = exo_m * 1_000_000

        # keep labels in sync
        try:
            self.exo_min_label.setText(f"{exo_m}M")
        except Exception:
            pass

        if action_state["exploration"]:
            lines.append(action_state["exploration"])

        if action_state["rings"]:
            lines.append(action_state["rings"])

        # _compute_action_state() is the single authority for all exobiology
        # Action lines (including "possible high-value exo genus") — this
        # used to also recompute the exact same high-value-genus check
        # independently here, producing two near-identical lines back to
        # back (one saying "DSS confirmed", one not, for the same bodies).
        if action_state["exobiology"]:
            lines.extend(action_state["exobiology"])

        # Only count "high value exo" when we have ScanOrganic-derived records (values may exist)
        exo_incomplete = 0
        exo_hv_incomplete = 0
        for _k, rec in (self.state.exo or {}).items():
            if not isinstance(rec, dict):
                continue
            last = (rec.get("LastScanType") or "").upper()
            if last == "CODEX":
                continue
            if rec.get("Complete"):
                continue
            exo_incomplete += 1
            base_v = rec.get("BaseValue")
            pot_v = rec.get("PotentialValue")
            hv = base_v if isinstance(base_v, int) else (pot_v if isinstance(pot_v, int) else None)
            if isinstance(hv, int) and hv >= exo_min:
                exo_hv_incomplete += 1

        if exo_incomplete:
            lines.append(f"🔬 Action: {exo_hv_incomplete} high-value exo incomplete (≥ {exo_m}M) | {exo_incomplete} exo incomplete")

        # Journal-derived system signals (NonBodyCount + discovered signal list)
        try:
            total = getattr(self.state, "system_body_count", None)
            # state.bodies includes both personally-scanned bodies and ones
            # backfilled from Spansh/DB cache -- resolved_body_ids only
            # counts personal Scan events, which under-counts (and can read
            # 0-1) for an already-catalogued system nobody's individually
            # scanned yet. "Unresolved" here means genuinely unknown (no
            # data from any source), not "not personally scanned by you".
            known = len(getattr(self.state, "bodies", {}) or {})
            # fss_complete tracks FSSDiscoveryScan's own Progress field (the
            # honk's scan-progress %, often 1.0 immediately) — not whether
            # every body has been individually resolved. Gating on it here
            # let it suppress this warning while bodies were still unresolved
            # (confirmed live: 8/10 resolved, fss_complete already True).
            if isinstance(total, int) and total > known:
                remaining = total - known
                lines.append(f"🔎 Action: {remaining} bodies unresolved (FSS)")
        except Exception:
            pass

        # Low-noise “POI-like” cues: surface only when we have discovered notable phenomena / megaships (journal-derived)
        try:
            sigs = getattr(self.state, "system_signals", None) or []
            phen = 0
            mega = 0
            tour = 0
            for s in sigs:
                if not isinstance(s, dict):
                    continue
                if s.get("Category") == "Phenomena":
                    phen += 1
                if s.get("Category") == "Megaship":
                    mega_key = MegashipTracker.key(getattr(self.state, "system_address", None), s.get("SignalName") or "")
                    if not self.megaship_tracker.has_seen(mega_key):
                        mega += 1
                if s.get("Category") == "TouristBeacon":
                    tour += 1
            if phen:
                lines.append(f"✨ Action: Stellar phenomena discovered ({phen})")
            if mega:
                lines.append(f"🚢 Action: Megaship signals discovered ({mega})")
            if tour:
                lines.append(f"✨ Action: Tourist Beacon discovered ({tour})")
        except Exception:
            pass

        # Geological (journal-derived; useful for material farming)
        try:
            geo_bodies = 0
            for _b, n in (getattr(self.state, "geo_signals", None) or {}).items():
                if isinstance(n, int) and n > 0:
                    geo_bodies += 1
            if geo_bodies:
                lines.append(f"🪨 Action: Geological signals on {geo_bodies} bodies")
        except Exception:
            pass

        # Materials shortlist (journal-derived; requires landable + Geo; improves “what do I land on first?”)
        try:
            mat_targets = 0
            mat_scanned = 0
            for _body, rec in (self.state.bodies or {}).items():
                if not isinstance(rec, dict):
                    continue
                landable = rec.get("Landable")
                if landable is not True:
                    continue
                geo = rec.get("GeoSignals", 0) or 0
                if not (isinstance(geo, int) and geo > 0):
                    continue
                mat_targets += 1

                mats = rec.get("Materials") or {}
                if isinstance(mats, dict) and any(isinstance(v, (int, float)) for v in mats.values()):
                    mat_scanned += 1

            if mat_targets > 0:
                if mat_scanned > 0:
                    lines.append(f"⛏️ Action: Materials shortlist ready ({mat_scanned}/{mat_targets} targets scanned)")
                else:
                    lines.append(f"⛏️ Action: Materials targets available ({mat_targets} landable geo) — scan bodies")
        except Exception:
            pass

        # Low-inventory RAW mats available in THIS system (journal-derived; requires Scan.Materials)
        try:
            low_threshold = 25
            inv_raw = getattr(self.state, "materials_raw", {}) or {}
            low_raw = set()
            if isinstance(inv_raw, dict):
                for k, v in inv_raw.items():
                    if isinstance(k, str) and isinstance(v, int) and v <= low_threshold:
                        low_raw.add(k.strip().lower())

            avail_keys = []
            if low_raw:
                for _body, rec in (self.state.bodies or {}).items():
                    if not isinstance(rec, dict):
                        continue
                    if rec.get("Landable") is not True:
                        continue
                    geo = rec.get("GeoSignals", 0) or 0
                    if not (isinstance(geo, int) and geo > 0):
                        continue
                    mats = rec.get("Materials") or {}
                    if not isinstance(mats, dict):
                        continue
                    for mk, pct in mats.items():
                        if not isinstance(mk, str) or not isinstance(pct, (int, float)):
                            continue
                        mk2 = mk.strip().lower()
                        if mk2 in low_raw and mk2 not in avail_keys:
                            avail_keys.append(mk2)

            if avail_keys:
                mats_loc = getattr(self.state, "materials_localised", {}) or {}
                names = []
                for key in avail_keys[:4]:
                    disp = mats_loc.get(key) if isinstance(mats_loc, dict) else None
                    disp = disp or key.replace("_", " ").title()
                    names.append(disp)
                tail = "…" if len(avail_keys) > 4 else ""
                lines.append(f"🧩 Action: Low RAW mats available in-system ({', '.join(names)}{tail})")
        except Exception:
            pass

        # Low materials inventory (journal-derived; independent of any planner)
        try:
            low_threshold = 25
            total_zero = 0
            total_low = 0
            for src_name in ("materials_raw", "materials_manufactured", "materials_encoded"):
                src = getattr(self.state, src_name, {}) or {}
                if not isinstance(src, dict):
                    continue
                for _k, v in src.items():
                    if not isinstance(v, int):
                        continue
                    if v == 0:
                        total_zero += 1
                    if v <= low_threshold:
                        total_low += 1
            if total_low > 0:
                lines.append(f"🧰 Action: Low materials stock (≤{low_threshold}) — {total_low} items ({total_zero} zero)")
        except Exception:
            pass

        # System-entry advisory hints (POIs + farming), once per system change
        self._maybe_add_system_intel_hints(lines)

        # Mirror only the action lines into Overview (clickable links to tabs)
        try:
            contact_lines = []
            action_lines = []
            intel_lines = []
            poi_lines = []
            seen = set()
            has_pp_action = False
            # PP enemy scan alerts (Overview only)
            # Contact Alert
            try:
                for alert in (getattr(self.state, "pp_enemy_alerts", None) or []):
                    if not isinstance(alert, dict):
                        continue
                    msg = alert.get("msg", "")
                    if msg and msg not in seen:
                        seen.add(msg)
                        contact_lines.append(
                            f'<span style="color:#FF4444;">⚠ {msg}</span>'
                        )
            except Exception:
                pass

            for ln in (lines or []):
                if not isinstance(ln, str) or not ln.strip():
                    continue
                if ln in seen:
                    continue
                seen.add(ln)
                ll = ln.lower()
                if "action:" in ll:
                    action_lines.append(ln)
                elif "intel:" in ll or "poi:" in ll:
                    intel_lines.append(ln)

            # PP action line
            pp_txt = getattr(self, "_pp_action_text", "") or ""
            if pp_txt:
                has_pp_action = True

            final_lines = []
            if contact_lines:
                final_lines.extend(contact_lines[:3])
            if action_lines:
                final_lines.extend(action_lines[:6])
            if intel_lines:
                final_lines.extend(intel_lines[:4])
            if has_pp_action:
                final_lines.append(pp_txt)

            self._animate_overview_update("<br>".join(final_lines))
        except Exception:
            pass

        # HUD should NOT duplicate Overview action lines; keep "Action:" hints in Overview only.
        hud_lines = []
        for ln in (lines or []):
            if not isinstance(ln, str):
                continue
            if ln.startswith("🌍 Action:") or ln.startswith("🔬 Action:") or ln.startswith("🧬 Action:") or ln.startswith("🛡️") or ln.startswith("🔎 Action:") or ln.startswith("🪨 Action:") or ln.startswith("⛏️ Action:") or ln.startswith("✨ Action:") or ln.startswith("🧩 Action:") or ln.startswith("📌 Intel:"):                continue
            hud_lines.append(ln)
        # Suppress Action lines from HUD (they belong in Overview panel)
        clean_lines = [ln for ln in lines if "Action:" not in ln]
        self.hud.setText("\n".join(clean_lines) if clean_lines else "Not connected")
        self._refresh_system_card()
        self._refresh_exploration()
        self._refresh_exobiology()
        self._refresh_powerplay()
        self._refresh_bounty_status()
        self._refresh_squadron_station()
        self._refresh_combat()
        self._refresh_squadron()
        self._refresh_intel()
        self._refresh_materials_inventory()
        self._refresh_shiplocker_inventory()
        self._refresh_engineering()
        self._refresh_fleet_carrier()
        self._refresh_mining()
        self._refresh_market()
        self.player_faction_panel.update_reference_state(self.state)

    def _animate_overview_update(self, html: str):
        self.overview_panel.animate_overview_update(html)

    def _refresh_shiplocker_inventory(self):
        self.shiplocker_panel.refresh(self.state, self.item_catalog)

    def _refresh_materials_inventory(self):
        self.materials_panel.refresh(self.state, self.item_catalog)

    def _refresh_engineering(self):
        self.engineering_panel.refresh(self.state)

    def _refresh_fleet_carrier(self):
        self.fleet_carrier_panel.refresh(self.state)

    def _refresh_mining(self):
        radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
        self.mining_panel.refresh(self.state, radius)

    def _refresh_market(self):
        radius = int(getattr(self.cfg, "market_search_radius_ly", 100) or 100)
        self.market_panel.refresh(self.state, radius)
        self.trade_route_panel.refresh(self.state)

    def _refresh_player_faction(self):
        self.player_faction_panel.refresh(self.state)

    def _on_mining_sell_search_requested(self, commodity_name: str):
        self.sidebar.setCurrentRow(self._market_tab_row)
        self.market_panel.search_for(commodity_name)

    def _on_squadron_buy_search_requested(self, commodity_name: str):
        self.sidebar.setCurrentRow(self._market_tab_row)
        self.market_panel.search_for(commodity_name, mode="buy")

    def _refresh_intel(self):
        system_address = getattr(self.state, "system_address", None)
        faction_history = []
        if isinstance(system_address, int):
            try:
                faction_history = self.repo.get_faction_history(system_address)
            except Exception:
                log.exception("Failed to load faction history")
        self.intel_panel.refresh(self.state, self.farming_locations, faction_history)

    def _refresh_combat(self):
        self.combat_panel.refresh(self.state)

    def _refresh_squadron(self):
        self.squadron_panel.refresh(self.state)

    def _refresh_bounty_status(self):
        """
        If a bounty is currently outstanding (CommitCrime with no matching
        PayBounties yet), find the closest station we've personally
        confirmed offers Interstellar Factors, excluding any station owned
        by an issuing faction — that station can't clear the bounty.
        """
        active = getattr(self.state, "active_bounties", None) or {}
        if not active:
            self.state.closest_interstellar_factors = None
            return
        x, y, z = self.state.system_x, self.state.system_y, self.state.system_z
        if not all(isinstance(v, (int, float)) for v in (x, y, z)):
            return
        try:
            self.state.closest_interstellar_factors = self.repo.find_closest_interstellar_factors(
                x, y, z, exclude_factions=list(active.keys())
            )
        except Exception:
            log.exception("Failed to find closest Interstellar Factors station")

    def _on_market_flush_tick(self) -> None:
        """
        Pops the buffered EDDN data (cheap, main-thread dict ops) and hands
        it to a background worker for the actual writes + WAL checkpoint —
        see _EddnFlushWorker for why this moved off the main thread.
        """
        if self._flush_thread and self._flush_thread.isRunning():
            return  # previous flush still running — next tick will catch up
        coords, market, factions, stations, codex = self.eddn_market_cache.pop_buffers()
        if not (coords or market or factions or stations or codex):
            return

        self._flush_worker = _EddnFlushWorker(self.repo.db.db_path, coords, market, factions, stations, codex)
        self._flush_thread = QThread()
        self._flush_worker.moveToThread(self._flush_thread)
        self._flush_thread.started.connect(self._flush_worker.run)
        self._flush_worker.finished.connect(self._flush_thread.quit)
        self._flush_thread.start()

    def _refresh_squadron_station(self):
        """
        Closest known station controlled by the squadron-aligned faction —
        combat bonds/bounty vouchers only credit that faction's BGS
        influence when redeemed at a station it actually controls.
        """
        faction = squadron_faction_name(getattr(self.state, "factions", None))
        if not faction:
            self.state.closest_squadron_station = None
            return
        x, y, z = self.state.system_x, self.state.system_y, self.state.system_z
        if not all(isinstance(v, (int, float)) for v in (x, y, z)):
            return
        try:
            self.state.closest_squadron_station = self.repo.find_closest_station_for_faction(x, y, z, faction)
        except Exception:
            log.exception("Failed to find closest squadron-faction station")

    def _refresh_powerplay(self):
        self.powerplay_panel.refresh(self.state, self.pp_activities)

    def _refresh_exobiology(self):
        self.exobiology_panel.refresh(
            self.state, self.cfg, self.exo_values, canonn_poi=self._canonn_poi
        )

    def _open_planet_detail(self, body_name: str):
        rec = self.state.bodies.get(body_name)
        if not isinstance(rec, dict):
            return
        from edc.ui.planet_detail_dialog import PlanetDetailDialog
        dlg = PlanetDetailDialog(body_name, rec, self.state, self)
        dlg.exec()

    def _refresh_exploration(self):
        spansh_rings = self._spansh_rings_by_system.get(
            getattr(self.state, "system_address", None)
        ) or []
        self.exploration_panel.refresh(
            self.state, self.cfg, self.planet_values, spansh_rings=spansh_rings
        )

    def _refresh_materials_shortlist(self):
        self.exploration_panel._refresh_materials_shortlist(self.state)

    def _norm_token(self, value):
        """Normalize Frontier-style token strings for display.

        Examples:
        '$SYSTEM_SECURITY_low;' -> 'Low'
        '$economy_Extraction;'  -> 'Extraction'
        '$government_Corporate;' -> 'Corporate'
        """
        s = fmt.text(value)
        if not s:
            return ""
        s = s.strip()
        if s.endswith(";"):
            s = s[:-1].strip()
        if s.startswith("$"):
            s = s[1:]
        # Drop common token prefixes, keep the meaningful tail
        if "_" in s:
            parts = [p for p in s.split("_") if p]
            if parts:
                s = parts[-1]
        s = s.replace("_", " ").strip()
        if not s:
            return ""
        # Preserve ALLCAPS abbreviations, otherwise Title-case first letter only
        if s.isupper():
            return s
        return s[:1].upper() + s[1:]

    def _refresh_system_card(self):
        self.overview_panel.refresh(self.state)

    def _clear_all_panels(self):
        """Clear all system-specific UI panels on jump."""
        try:
            self.overview_panel.refresh(self.state)
        except Exception:
            pass
        try:
            self.exploration_panel.refresh(
                self.state, self.cfg, self.planet_values
            )
        except Exception:
            pass
        try:
            self.exobiology_panel.refresh(
                self.state, self.cfg, self.exo_values, canonn_poi=self._canonn_poi
            )
        except Exception:
            pass
        try:
            self.combat_panel.refresh(self.state)
        except Exception:
            pass
        try:
            self.powerplay_panel.refresh(self.state, self.pp_activities)
        except Exception:
            pass
        try:
            self.intel_panel.refresh(
                self.state, self.farming_locations
            )
        except Exception:
            pass

    def _compute_action_state(self):
        """
        Single authority for all 'Action:' decisions.
        Returns a dict with preformatted action strings or None.
        """
        out = {
            "exploration": None,
            "exobiology": [],
            "rings": None,
        }

        try:
            min_100k = int(getattr(self.cfg, "min_planet_value_100k", 5) or 5)
            if min_100k < 0:
                min_100k = 0
            min_value = min_100k * 100_000

            exo_m = int(getattr(self.cfg, "exo_high_value_m", 2) or 2)
            exo_min = exo_m * 1_000_000
        except Exception:
            return out

        hv_unmapped = 0
        tf_unmapped = 0
        bio_need_dss = 0

        genus_max = {}
        if self.exo_values:
            for rec in self.exo_values.by_species.values():
                g = rec.genus
                v = rec.base_value
                if isinstance(g, str) and isinstance(v, int):
                    genus_max[g] = max(v, genus_max.get(g, 0))

        # Species are deterministic per body — if another commander (or us,
        # via our own EDDN publish loopback) already logged a biology
        # CodexEntry here, we know the exact species and value before ever
        # personally running a DSS, unlike the generic genus-range guess
        # below that's all we have for a body nobody's reported yet.
        system_address = getattr(self.state, "system_address", None)
        codex_sightings = (
            self.repo.get_codex_species_sightings_for_system(system_address)
            if isinstance(system_address, int) else {}
        )
        confirmed_species: list[tuple[str, Optional[int]]] = []

        for _body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue

            est = rec.get("EstimatedValue")
            dss_mapped = bool(rec.get("DSSMapped", False)) or bool(rec.get("BioGenuses"))
            tf = bool(rec.get("Terraformable", False))

            bio = rec.get("BioSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []

            if tf and not dss_mapped:
                tf_unmapped += 1

            if isinstance(est, int) and est >= min_value and not dss_mapped:
                hv_unmapped += 1

            if isinstance(bio, int) and bio > 0 and not gen:
                sighting = codex_sightings.get(rec.get("BodyID"))
                if sighting:
                    species_name = sighting["species_name"]
                    value = self.exo_values.get_value(species_name) if self.exo_values else None
                    confirmed_species.append((species_name, value))
                else:
                    bio_need_dss += 1

        if hv_unmapped > 0 or tf_unmapped > 0:
            out["exploration"] = (
                f"🌍 Action: {hv_unmapped} bodies worth mapping (FSS) | {tf_unmapped} TF unmapped"
            )

        if confirmed_species:
            parts = [
                f"{name} (~{value / 1_000_000:.1f}M)" if isinstance(value, int) else name
                for name, value in confirmed_species[:3]
            ]
            more = len(confirmed_species) - 3
            suffix = f" +{more} more" if more > 0 else ""
            out["exobiology"].append(
                f"🔬 Action: {len(confirmed_species)} bod{'y' if len(confirmed_species) == 1 else 'ies'} "
                f"EDDN-confirmed before DSS — {', '.join(parts)}{suffix} — worth landing to scan"
            )

        # Rings with no hotspot data anywhere — checked against Spansh
        # (community/EDDN) once per system via _maybe_start_ring_hotspot_check(),
        # but Spansh's snapshot goes stale the moment you personally DSS a
        # ring yourself: EDDN->Spansh ingestion lags (observed: even minutes
        # after a real scan, Spansh still showed it as ungathered), so a
        # ring this commander has already scanned this session must also be
        # excluded here even if Spansh hasn't caught up yet.
        spansh_rings = self._spansh_rings_by_system.get(system_address) or []
        personally_scanned = {
            name for name, rec in (self.state.rings or {}).items()
            if isinstance(rec, dict) and rec.get("system_address") == system_address and rec.get("scanned")
        }
        ring_gaps = [
            r for r in spansh_rings
            if not r.get("signals") and r.get("ring_name") not in personally_scanned
        ]
        if ring_gaps:
            out["rings"] = (
                f"💍 Action: {len(ring_gaps)} ring{'s' if len(ring_gaps) != 1 else ''} here "
                f"missing hotspot data anywhere (Spansh/EDDN) — DSS it to be first to report"
            )

        dss_hv = 0
        for _body, rec in (self.state.bodies or {}).items():
            gen = rec.get("BioGenuses", []) or []
            for g in gen:
                if genus_max.get(g, 0) >= exo_min:
                    dss_hv += 1
                    break

        # One combined line for "genus not yet known" vs "genus known and
        # high-value" — these used to be two separate bullet lines with
        # near-identical wording (only "DSS confirmed" distinguishing
        # them), which read as duplicate/overlapping notifications even
        # though they describe disjoint sets of bodies (unscanned vs
        # already-scanned).
        if bio_need_dss > 0 or dss_hv > 0:
            bits = []
            if bio_need_dss > 0:
                bits.append(f"{bio_need_dss} unidentified — DSS/map to reveal genus")
            if dss_hv > 0:
                bits.append(f"{dss_hv} DSS-confirmed high-value (≥ {exo_m}M)")
            out["exobiology"].append(f"🔬 Action: Exobiology — {' | '.join(bits)}")

        return out

    def _append(self, text: str):
        self.log_box.append(text)
        # Keep the UI log bounded (long play sessions otherwise grow unbounded).
        try:
            doc = self.log_box.document()
            max_blocks = 2000
            excess = doc.blockCount() - max_blocks
            if excess > 0:
                cur = QTextCursor(doc)
                cur.movePosition(QTextCursor.MoveOperation.Start)
                # Remove oldest blocks first
                for _ in range(excess):
                    cur.select(QTextCursor.SelectionType.BlockUnderCursor)
                    cur.removeSelectedText()
                    cur.deleteChar()  # remove the newline after the block
        except Exception:
            pass
