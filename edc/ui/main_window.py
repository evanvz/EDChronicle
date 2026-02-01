import logging
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QSplitter,
)
from PyQt6.QtCore import QThread, Qt, QTimer
from PyQt6.QtGui import QTextCursor
from pathlib import Path

from edc.core.state import GameState
from edc.core.event_engine import EventEngine
from edc.core.journal_watcher import JournalWatcher
from edc.core.status_watcher import StatusWatcher
from edc.core.planet_values import PlanetValueTable
from edc.core.exo_values import ExoValueTable
from edc.core.external_intel import ExternalIntel
from edc.core.item_catalog import ItemCatalog
from edc.core.farming_locations import FarmingLocations
from edc.ui import formatting as fmt
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.ui.main")

class MainWindow(QMainWindow):
    def __init__(self, cfg_store, cfg):
        super().__init__()
        self.cfg_store = cfg_store
        self.cfg = cfg

        self.setWindowTitle("ED Companion (Fresh Build)")
        self.resize(1000, 650)

        self.state = GameState()

        # Canonical paths: app_dir for shipped assets, settings_dir for writable JSON/caches.
        app_dir = Path(getattr(self.cfg_store, "app_dir", Path.cwd()))
        settings_base = Path(getattr(self.cfg_store, "settings_dir", app_dir / "settings"))

        # Load value tables from the canonical app_dir only (no Path.cwd fallbacks).
        self.planet_values = PlanetValueTable.load_from_paths(app_dir / "planet_values.json")
        self.exo_values = ExoValueTable.load_from_paths(app_dir / "exo_values.json")

        log.info("MainWindow paths: app_dir=%s settings_dir=%s", str(app_dir), str(settings_base))

        self.external_intel = ExternalIntel(settings_base)
        self.item_catalog = ItemCatalog(settings_base)
        self.farming_locations = FarmingLocations(settings_base)
        self.engine = EventEngine(
            self.state,
            planet_values=self.planet_values,
            exo_values=self.exo_values,
            external_intel=self.external_intel,
        )

        self.thread: QThread | None = None
        self.watcher: JournalWatcher | None = None
        self.status_thread: QThread | None = None
        self.status_watcher: StatusWatcher | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        self.hud = QLabel("Not connected")
        self.status = QLabel("Status: idle")

        self.overview_actions = QLabel("")
        self.overview_actions.setWordWrap(True)
        self.overview_actions.setTextFormat(Qt.TextFormat.RichText)
        self.overview_actions.setOpenExternalLinks(False)
        self.overview_actions.linkActivated.connect(self._on_overview_action_link)

        self.system_card = QTextEdit()
        self.system_card.setReadOnly(True)
        self.system_card.setMinimumHeight(220)

        self.factions_table = QTableWidget()
        self.factions_table.setColumnCount(4)
        self.factions_table.setHorizontalHeaderLabels(["Faction", "Influence", "State", "Rep"])
        self.factions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.factions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.factions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.factions_table.verticalHeader().setVisible(False)
        self.factions_table.setShowGrid(False)
        self.factions_table.setAlternatingRowColors(True)
        self.factions_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.factions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.setMinimumHeight(180)

        self.exploration_table = QTableWidget()
        self.exploration_table.setColumnCount(8)
        self.exploration_table.setHorizontalHeaderLabels(["Body", "Class", "LS", "Bio", "Geo", "Genera", "Est. Value", "Tags"])
        self.exploration_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.exploration_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.exploration_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.exploration_table.verticalHeader().setVisible(False)
        self.exploration_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.exploration_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.exploration_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.setMinimumHeight(220)
        self.exploration_table.setSortingEnabled(True)
        self.exploration_action = QLabel("")
        self.exploration_action.setWordWrap(True)
        self.exploration_hint = QLabel("")
        self.exploration_hint.setWordWrap(True)
        self.system_signals_box = QTextEdit()
        self.system_signals_box.setReadOnly(True)
        self.system_signals_box.setMinimumHeight(110)
        self.system_signals_box.setPlaceholderText("System signals will appear here after FSSSignalDiscovered events.")
        self.materials_box = QTextEdit()
        self.materials_box.setReadOnly(True)
        self.materials_box.setMinimumHeight(130)
        self.materials_box.setPlaceholderText("Materials shortlist will appear here once landable bodies are scanned (Scan event includes Materials/Volcanism).")

        # Intel (external / advisory)
        self.intel_summary = QLabel("")
        self.intel_summary.setWordWrap(True)
        self.intel_box = QTextEdit()
        self.intel_box.setReadOnly(True)

        # Exobiology
        self.exo_table = QTableWidget()
        self.exo_table.setColumnCount(8)
        self.exo_table.setHorizontalHeaderLabels(
            ["Body", "Genus", "Species", "Variant", "Potential", "Base Value", "Samples", "Status"]
        )
        self.exo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.exo_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.exo_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.exo_table.verticalHeader().setVisible(False)
        self.exo_table.setSortingEnabled(True)
        self.exo_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.exo_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.exo_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.exo_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Variant
        self.exo_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Potential
        self.exo_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Base Value
        self.exo_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Samples
        self.exo_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # Status
        self.exo_table.setMinimumHeight(200)
        self.exo_action = QLabel("")
        self.exo_action.setWordWrap(True)
        self.exo_hint = QLabel("")
        self.exo_hint.setWordWrap(True)

        # PowerPlay tab widgets
        self.pp_summary = QLabel("")
        self.pp_summary.setWordWrap(True)
        self.pp_actions = QLabel("")
        self.pp_actions.setWordWrap(True)

        self.pp_progress = QTableWidget()
        self.pp_progress.setColumnCount(2)
        self.pp_progress.setHorizontalHeaderLabels(["Power", "Conflict %"])
        self.pp_progress.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pp_progress.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.pp_progress.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.pp_progress.verticalHeader().setVisible(False)
        self.pp_progress.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.pp_progress.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.pp_progress.setMinimumHeight(180)

        # Combat (stub)
        self.combat_hint = QLabel("Scanned contacts will appear here once you fully scan a ship (ScanStage ≥ 3).")
        self.combat_hint.setWordWrap(True)

        self.combat_table = QTableWidget()
        self.combat_table.setColumnCount(8)
        self.combat_table.setHorizontalHeaderLabels(
            ["Pilot", "Rank", "Ship", "Faction", "Power", "Wanted", "Bounty", "Last Seen"]
        )
        self.combat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.combat_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.combat_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.combat_table.verticalHeader().setVisible(False)
        self.combat_table.setSortingEnabled(True)
        self.combat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.combat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.combat_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.combat_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.combat_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.combat_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.combat_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.combat_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.combat_table.setMinimumHeight(220)

        self.min_value_label = QLabel()
        self.min_value_slider = QSlider()
        self.min_value_slider.setOrientation(Qt.Orientation.Horizontal)
        self.min_value_slider.setMinimum(0)
        # 0..200 => 0.0M .. 20.0M in steps of 0.1M (100k credits)
        self.min_value_slider.setMaximum(200)
        self.min_value_slider.setValue(int(getattr(self.cfg, "min_planet_value_100k", 10) or 10))
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

        btn_start = QPushButton("Start Watching Journals")
        btn_stop = QPushButton("Stop")

        layout.addWidget(self.hud)
        layout.addWidget(self.status)

        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_start)
        btn_row.addWidget(btn_stop)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.tabs = tabs

        # Overview tab (System Card)
        tab_overview = QWidget()
        ov = QVBoxLayout(tab_overview)
        ov.addWidget(self.overview_actions)
        top_label = QLabel("System")
        bottom_label = QLabel("Factions (top by influence)")
        top_label.setContentsMargins(0, 0, 0, 0)
        bottom_label.setContentsMargins(0, 0, 0, 0)

        top_panel = QWidget()
        top_l = QVBoxLayout(top_panel)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.addWidget(top_label)
        top_l.addWidget(self.system_card)

        bottom_panel = QWidget()
        bot_l = QVBoxLayout(bottom_panel)
        bot_l.setContentsMargins(0, 0, 0, 0)
        bot_l.addWidget(bottom_label)
        bot_l.addWidget(self.factions_table)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top_panel)
        split.addWidget(bottom_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        ov.addWidget(split)
        self.tab_overview_idx = tabs.addTab(tab_overview, "Overview")

        # Exploration tab
        tab_explore = QWidget()
        ex = QVBoxLayout(tab_explore)
        ex.addWidget(QLabel("Exploration (scans → instant estimate)"))
        ex.addWidget(self.exploration_action)
        ex.addWidget(self.exploration_table)
        ex.addWidget(QLabel("System signals (FSS)"))
        ex.addWidget(self.system_signals_box)
        ex.addWidget(QLabel("Materials shortlist (landable + Geo signals)"))
        ex.addWidget(self.materials_box)
        ex.addWidget(self.exploration_hint)
        self.tab_explore_idx = tabs.addTab(tab_explore, "Exploration")

        # Exobiology tab
        tab_exo = QWidget()
        xb = QVBoxLayout(tab_exo)
        xb.addWidget(QLabel("Exobiology"))
        xb.addWidget(self.exo_action)
        xb.addWidget(self.exo_table, 1)
        self.tab_exo_idx = tabs.addTab(tab_exo, "Exobiology")

        # PowerPlay tab
        tab_pp = QWidget()
        pp = QVBoxLayout(tab_pp)
        pp.addWidget(QLabel("PowerPlay"))
        pp.addWidget(self.pp_summary)
        pp.addWidget(self.pp_actions)
        pp.addWidget(QLabel("Conflict progress (if present)"))
        pp.addWidget(self.pp_progress, 1)
        self.tab_pp_idx = tabs.addTab(tab_pp, "PowerPlay")

        # Combat tab (stub)
        tab_combat = QWidget()
        cb = QVBoxLayout(tab_combat)
        cb.addWidget(QLabel("Combat"))
        cb.addWidget(self.combat_hint)
        cb.addWidget(self.combat_table, 1)
        self.tab_combat_idx = tabs.addTab(tab_combat, "Combat")

        # Intel tab (external / advisory)
        tab_intel = QWidget()
        it = QVBoxLayout(tab_intel)
        it.addWidget(QLabel("Intel (External, advisory only)"))
        it.addWidget(self.intel_summary)
        it.addWidget(self.intel_box, 1)
        self.tab_intel_idx = tabs.addTab(tab_intel, "Intel")

        # Odyssey tab (ShipLocker inventory; journal-derived)
        self.ody_summary = QLabel("")
        self.ody_summary.setWordWrap(True)
        self.ody_filter = QLineEdit()
        self.ody_filter.setPlaceholderText("Filter (e.g. schematic, data, health, ionised...)")

        self.ody_table = QTableWidget()
        self.ody_table.setColumnCount(3)
        self.ody_table.setHorizontalHeaderLabels(["Item", "Subtype", "Count"])
        self.ody_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ody_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ody_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.ody_table.verticalHeader().setVisible(False)
        self.ody_table.setShowGrid(False)
        self.ody_table.setAlternatingRowColors(True)
        self.ody_table.setSortingEnabled(True)
        self.ody_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.ody_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.ody_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.ody_table.setMinimumHeight(240)

        tab_ody = QWidget()
        oy = QVBoxLayout(tab_ody)
        oy.addWidget(QLabel("Odyssey (Ship Locker inventory; journal-derived)"))
        oy.addWidget(self.ody_filter)
        oy.addWidget(self.ody_summary)
        oy.addWidget(self.ody_table, 1)
        self.tab_ody_idx = tabs.addTab(tab_ody, "Odyssey")

        # Materials tab (journal-derived inventory snapshot)
        self.inv_summary = QLabel("")
        self.inv_summary.setWordWrap(True)
        self.inv_kind = QComboBox()
        self.inv_kind.addItems(["Raw", "Manufactured", "Encoded"])
        self.inv_filter = QLineEdit()
        self.inv_filter.setPlaceholderText("Filter (e.g. selenium, polymer, wake...)")

        self.inv_table = QTableWidget()
        self.inv_table.setColumnCount(3)
        self.inv_table.setHorizontalHeaderLabels(["Material", "Subtype", "Count"])
        self.inv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.inv_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.inv_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.inv_table.verticalHeader().setVisible(False)
        self.inv_table.setShowGrid(False)
        self.inv_table.setAlternatingRowColors(True)
        self.inv_table.setSortingEnabled(True)
        self.inv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.inv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.inv_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.inv_table.setMinimumHeight(240)

        tab_mats = QWidget()
        mt = QVBoxLayout(tab_mats)
        mt.addWidget(QLabel("Materials (Commander inventory; journal-derived)"))

        rowm = QHBoxLayout()
        rowm.addWidget(QLabel("Category:"))
        rowm.addWidget(self.inv_kind)
        rowm.addWidget(QLabel("Filter:"))
        rowm.addWidget(self.inv_filter, 1)
        mt.addLayout(rowm)

        mt.addWidget(self.inv_summary)
        mt.addWidget(self.inv_table, 1)
        self.tab_materials_idx = tabs.addTab(tab_mats, "Materials")

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

        st.addStretch(1)
        self.tab_settings_idx = tabs.addTab(tab_settings, "Settings")

        # Log tab
        tab_log = QWidget()
        lg = QVBoxLayout(tab_log)
        lg.addWidget(QLabel("Log"))
        lg.addWidget(self.log_box)
        self.tab_log_idx = tabs.addTab(tab_log, "Log")

        layout.addWidget(tabs)

        btn_start.clicked.connect(self.start_watching)
        btn_stop.clicked.connect(self.stop_watching)
        btn_browse.clicked.connect(self._browse_journal_dir)
        self.settings_journal_edit.editingFinished.connect(self._on_settings_journal_changed)
        self.inv_kind.currentIndexChanged.connect(self._refresh_materials_inventory)
        self.inv_filter.textChanged.connect(self._refresh_materials_inventory)
        self.ody_filter.textChanged.connect(self._refresh_shiplocker_inventory)

        # ---- Intel hint suppression (show once per system change) ----
        self._last_intel_system_key: str = ""

        # ---- UI refresh debounce (journal bursts can be spammy) ----
        self._hud_refresh_pending = False
        self._hud_refresh_timer = QTimer(self)
        self._hud_refresh_timer.setSingleShot(True)
        self._hud_refresh_timer.timeout.connect(self._do_hud_refresh)

        self._refresh_hud()
        self._auto_start_if_configured()

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
        # Jump to the relevant tab (no auto-scroll / no selection)
        try:
            if link == "exploration":
                self.tabs.setCurrentIndex(self.tab_explore_idx)
            elif link == "exobiology":
                self.tabs.setCurrentIndex(self.tab_exo_idx)
            elif link == "powerplay":
                self.tabs.setCurrentIndex(self.tab_pp_idx)
            elif link == "intel":
                self.tabs.setCurrentIndex(self.tab_intel_idx)
            elif link == "materials":
                self.tabs.setCurrentIndex(self.tab_materials_idx)
        except Exception:
            pass

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
                QMessageBox.warning(self, "Invalid folder", "That folder doesn’t exist.")
            else:
                self.status.setText("Status: journal folder invalid (set in Settings)")
            return

        # Stop any existing watcher cleanly
        self.stop_watching()

        self.thread = QThread()
        self.watcher = JournalWatcher(journal_path)
        self.watcher.moveToThread(self.thread)

        self.thread.started.connect(self.watcher.run)
        self.watcher.status.connect(self._on_status)
        self.watcher.error.connect(self._on_error)
        self.watcher.event_received.connect(self._on_event)

        self.thread.start()
        self.status.setText(f"Status: watching {journal_path}")
        self._append(f"Started watching: {journal_path}")

        # Status.json watcher (for live lat/lon + CCR)
        try:
            status_path = journal_path / "Status.json"
            self.status_thread = QThread()
            self.status_watcher = StatusWatcher(status_path)
            self.status_watcher.moveToThread(self.status_thread)

            self.status_thread.started.connect(self.status_watcher.run)
            self.status_watcher.error.connect(self._on_error)
            # Don't spam the UI status bar with status.json messages; keep it quiet.
            self.status_watcher.event_received.connect(self._on_event)

            self.status_thread.start()
            self._append(f"Started watching status: {status_path}")
        except Exception:
            pass

    def stop_watching(self):
        if self.watcher:
            self.watcher.stop()

        if self.thread:
            self.thread.quit()
            self.thread.wait(1500)

        if self.status_watcher:
            self.status_watcher.stop()

        if self.status_thread:
            self.status_thread.quit()
            self.status_thread.wait(1500)

        self.thread = None
        self.watcher = None
        self.status_thread = None
        self.status_watcher = None
        self.status.setText("Status: stopped")

    def closeEvent(self, event):
        self.stop_watching()
        super().closeEvent(event)

    def _on_status(self, msg: str):
        self.status.setText(f"Status: {msg}")
        self._append(msg)

    def _on_error(self, msg: str):
        self._append(f"[ERROR] {msg}")

    def _on_event(self, evt: dict):
        name = evt.get("event", "UNKNOWN")
        self._append(f"[EVENT] {name}")
        state, msgs = self.engine.process(evt)
        self.state = state
        for m in msgs:
            self._append(m)
        self._schedule_hud_refresh()

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
        """
        Single authority for "what should I do here?" PowerPlay action text.
        Keeps HUD + PowerPlay tab consistent and avoids drift.
        """
        if not pledged:
            return ""

        friendly = bool(ctrl and ctrl == pledged)
        enemy = bool(ctrl and ctrl != pledged)
        st = (pp_state or "").strip()
        pows = powers if isinstance(powers, list) else []

        # State-driven guidance first (more specific)
        if st in ("Fortified", "Stronghold"):
            if friendly:
                return "Fortify/defend: run PP logistics and defensive activities for your power."
            if enemy:
                return "Enemy Stronghold: expect PP opposition; avoid or undermine (if you choose)."
            return "Fortified/stronghold activity present: stay alert."

        if st == "Contested":
            if friendly:
                return "Contested: support your power’s conflict effort here."
            if enemy:
                return "Contested (enemy): higher risk; avoid or oppose (if you choose)."
            return "Contested: higher risk; PP conflict activity likely."

        if st == "Unoccupied":
            if pledged in pows:
                return "Unoccupied: your power is present; watch progress and support objectives if desired."
            return "Unoccupied: no clear PP objective; treat as neutral space."

        # Fallback guidance if we have relationship but no specific state
        if enemy:
            return "Enemy space: stay alert for PP opposition."
        if friendly:
            return "Friendly space: PP objectives may be available."
        return ""

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
            powers = getattr(self.state, "system_powers", None) or []

            action = self._derive_pp_action(pledged, ctrl, pp_state, powers)
            if action:
                self._pp_action_text = f"PP Action: {action}"
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
                if ctrl and ctrl == pledged:
                    lines.append(f"🟢 PP: Friendly space ({ctrl}) — {pp_state or 'Active'}")
                elif ctrl and ctrl != pledged:
                    lines.append(f"🔴 PP: Enemy-controlled ({ctrl}) — {pp_state or 'Active'} (caution)")
                else:
                    ptxt = ", ".join([p for p in pw[:3] if isinstance(p, str)])
                    extra = f" | Powers: {ptxt}" if ptxt else ""
                    lines.append(f"🟡 PP: {pp_state or 'Active'}{extra}")

                # --- Action hint (Overview only) ---
                s = str(pp_state or "").lower()
                friendly = bool(ctrl and ctrl == pledged)
                enemy = bool(ctrl and ctrl != pledged)

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

            bits = [f"CG: {title}"]
            if loc:
                bits.append(loc)
            if tier_txt:
                bits.append(f"Tier {tier_txt}")
            bits.append(f"You {pc_txt}")
            if exp:
                bits.append(f"Ends {exp}")
            lines.append(" | ".join(bits))

        # Session ledger (gross totals for this app run)
        cod_col = int(getattr(self.state, "session_codex_collected", 0) or 0)
        cod_sold = int(getattr(self.state, "session_codex_earnings", 0) or 0)

        if cod_col > 0 or cod_sold > 0:
            lines.append(f"Codex | Collected: {cod_col:,} cr | Sold: {cod_sold:,} cr")
        # One-line "action hints" (what's worth doing in THIS system)
        try:
            min_100k = int(getattr(self.cfg, "min_planet_value_100k", 10) or 10)
        except Exception:
            min_100k = 10
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

        # Build genus -> max known species value map (from exo_values.json)
        genus_max_value = {}
        if self.exo_values:
            for rec in self.exo_values.by_species.values():
                g = rec.genus
                v = rec.base_value
                if isinstance(g, str) and isinstance(v, int):
                    prev = genus_max_value.get(g)
                    if prev is None or v > prev:
                        genus_max_value[g] = v
        if action_state["exploration"]:
            lines.append(action_state["exploration"])


        # Exobiology: split "bio signals exist" vs "we have real exobio targets/values"
        # Bio signals from FSS may not include genus until DSS/mapping events arrive.
        bio_need_dss = 0
        for _body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue
            bio = rec.get("BioSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []
            if isinstance(bio, int) and bio > 0 and not gen:
                bio_need_dss += 1

        if action_state["exobiology"]:
            lines.extend(action_state["exobiology"])

        # DSS-confirmed genus → possible high-value exo (potential, not guaranteed)
        dss_hv_genus_bodies = 0
        for _body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue
            gen = rec.get("BioGenuses", []) or []
            if not gen:
                continue
            for g in gen:
                max_v = genus_max_value.get(g)
                if isinstance(max_v, int) and max_v >= exo_min:
                    dss_hv_genus_bodies += 1
                    break

        if dss_hv_genus_bodies:
            lines.append(
                f"🔬 Action: {dss_hv_genus_bodies} bodies with possible high-value exo genus (DSS confirmed, ≥ {exo_m}M)"
            )

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
            nb = getattr(self.state, "non_body_count", None)
            sigs = getattr(self.state, "system_signals", None) or []
            if isinstance(nb, int) and nb > 0 and not sigs:
                lines.append(f"🔎 Action: {nb} non-body signals present (FSS)")
        except Exception:
            pass

        # Low-noise “POI-like” cues: surface only when we have discovered notable phenomena / megaships (journal-derived)
        try:
            sigs = getattr(self.state, "system_signals", None) or []
            phen = 0
            mega = 0
            for s in sigs:
                if not isinstance(s, dict):
                    continue
                if s.get("Category") == "Phenomena":
                    phen += 1
                if s.get("Category") == "Megaship":
                    mega += 1
            if phen:
                lines.append(f"✨ Action: Stellar phenomena discovered ({phen})")
            if mega:
                lines.append(f"🚢 Action: Megaship signals discovered ({mega})")
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
            html_lines = []
            has_pp_action = False
            # PP enemy scan alerts (Overview only)
            try:
                cur = getattr(self.state, "current_contact_alert", "") or ""
                if isinstance(cur, str) and cur.strip():
                    safe = cur.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    html_lines.append(safe)
            except Exception:
                pass
            for ln in lines:
                if not isinstance(ln, str):
                    continue
                if ln.startswith("🌍 Action:"):
                    html_lines.append(f'<a href="exploration">{ln}</a>')
                elif ln.startswith("🔬 Action:"):
                    html_lines.append(f'<a href="exobiology">{ln}</a>')
                elif ln.startswith("🔎 Action:") or ln.startswith("🪨 Action:") or ln.startswith("⛏️ Action:") or ln.startswith("✨ Action:"):
                    html_lines.append(f'<a href="exploration">{ln}</a>')
                elif ln.startswith("🧩 Action:"):
                    html_lines.append(f'<a href="exploration">{ln}</a>')
                elif ln.startswith("📌 Intel:"):
                    html_lines.append(f'<a href="intel">{ln}</a>')
                elif ln.startswith("🧰 Action:"):
                    html_lines.append(f'<a href="materials">{ln}</a>')
                elif ln.startswith("⛏️ Intel:"):
                    html_lines.append(f'<a href="intel">{ln}</a>')
            if getattr(self, "_pp_action_text", ""):
                html_lines.append(f'<a href="powerplay">🛡️ {self._pp_action_text}</a>')
            self.overview_actions.setText("<br>".join(html_lines))
        except Exception:
            pass

        # HUD should NOT duplicate Overview action lines; keep "Action:" hints in Overview only.
        hud_lines = []
        for ln in (lines or []):
            if not isinstance(ln, str):
                continue
            if ln.startswith("🌍 Action:") or ln.startswith("🔬 Action:") or ln.startswith("🧬 Action:") or ln.startswith("🛡️") or ln.startswith("🔎 Action:") or ln.startswith("🪨 Action:") or ln.startswith("⛏️ Action:") or ln.startswith("✨ Action:") or ln.startswith("🧩 Action:") or ln.startswith("📌 Intel:"):                continue
            hud_lines.append(ln)
        self.hud.setText("\n".join(hud_lines) if hud_lines else "Not connected")
        self._refresh_system_card()
        self._refresh_exploration()
        self._refresh_exobiology()
        self._refresh_powerplay()
        self._refresh_combat()
        self._refresh_intel()
        self._refresh_materials_inventory()
        self._refresh_shiplocker_inventory()

    def _refresh_shiplocker_inventory(self):
        """
        Odyssey ShipLocker inventory snapshot (from ShipLocker journal event).
        """
        try:
            src = getattr(self.state, "shiplocker_items", {}) or {}
            localised = getattr(self.state, "shiplocker_localised", {}) or {}
            if not isinstance(src, dict) or not src:
                self.ody_summary.setText(
                    "No ShipLocker inventory loaded yet.\n"
                    "Tip: open the on-foot inventory/locker screen or relog so a 'ShipLocker' journal event is emitted."
                )
                self.ody_table.setRowCount(0)
                return

            filt = (self.ody_filter.text() or "").strip().lower()
            rows = []
            for nm, cnt in src.items():
                if not isinstance(nm, str) or not isinstance(cnt, int):
                    continue
                key = nm.strip().lower()
                disp = localised.get(key) or key.replace("_", " ").title()
                if filt and (filt not in key and filt not in disp.lower()):
                    continue
                subtype = ""
                try:
                    subtype = self.item_catalog.get_subtype_label(disp) or ""
                except Exception:
                    subtype = ""
                rows.append((cnt, disp, subtype))

            rows.sort(key=lambda x: (x[0], x[1].lower()))
            self.ody_table.setSortingEnabled(False)
            self.ody_table.setRowCount(len(rows))
            for r, (cnt, disp, subtype) in enumerate(rows):
                self.ody_table.setItem(r, 0, QTableWidgetItem(disp))
                self.ody_table.setItem(r, 1, QTableWidgetItem(str(subtype or "")))
                self.ody_table.setItem(r, 2, QTableWidgetItem(str(cnt)))
            self.ody_table.setSortingEnabled(True)

            ts = getattr(self.state, "shiplocker_last_update", None)
            ts_txt = f"Updated: {ts}" if isinstance(ts, str) and ts.strip() else "Updated: (unknown)"
            cat_txt = ""
            try:
                if self.item_catalog.has_data():
                    lu = getattr(self.item_catalog, "last_updated", None)
                    lu_txt = f", updated {lu}" if isinstance(lu, str) and lu.strip() else ""
                    cat_txt = f" | Catalog: {self.item_catalog.count()}{lu_txt}"
            except Exception:
                cat_txt = ""
            self.ody_summary.setText(f"{ts_txt} | Items: {len(src)}{cat_txt}")
        except Exception:
            try:
                self.ody_summary.setText("")
                self.ody_table.setRowCount(0)
            except Exception:
                pass

    def _refresh_materials_inventory(self):
        """
        Commander inventory snapshot (from Materials journal event).
        """
        try:
            kind = self.inv_kind.currentText() if hasattr(self, "inv_kind") else "Raw"
            filt = (self.inv_filter.text() or "").strip().lower() if hasattr(self, "inv_filter") else ""

            src = {}
            if kind == "Raw":
                src = getattr(self.state, "materials_raw", {}) or {}
            elif kind == "Manufactured":
                src = getattr(self.state, "materials_manufactured", {}) or {}
            elif kind == "Encoded":
                src = getattr(self.state, "materials_encoded", {}) or {}

            if not isinstance(src, dict) or not src:
                tip = (
                    "No materials inventory loaded yet.\n"
                    "Tip: open the in-game Inventory/Materials screen or relog so a 'Materials' journal event is emitted."
                )
                self.inv_summary.setText(tip)
                self.inv_table.setRowCount(0)
                return

            localised = getattr(self.state, "materials_localised", {}) or {}
            if not isinstance(localised, dict):
                localised = {}

            rows = []
            zero = 0
            low_threshold = 25
            low = 0

            for nm, cnt in src.items():
                if not isinstance(nm, str) or not isinstance(cnt, int):
                    continue
                key = nm.strip().lower()
                disp = localised.get(key) or key.replace("_", " ").title()
                if filt and (filt not in key and filt not in disp.lower()):
                    continue
                if cnt == 0:
                    zero += 1
                if cnt <= low_threshold:
                    low += 1
                subtype = ""
                try:
                    subtype = self.item_catalog.get_subtype_label(disp) or ""
                except Exception:
                    subtype = ""
                rows.append((cnt, disp, subtype, key))

            rows.sort(key=lambda x: (x[0], x[1].lower()))  # low-first by default; user can sort in UI

            self.inv_table.setSortingEnabled(False)
            self.inv_table.setRowCount(len(rows))
            for r, (cnt, disp, subtype, _key) in enumerate(rows):
                self.inv_table.setItem(r, 0, QTableWidgetItem(disp))
                self.inv_table.setItem(r, 1, QTableWidgetItem(str(subtype or "")))
                self.inv_table.setItem(r, 2, QTableWidgetItem(str(cnt)))
            self.inv_table.setSortingEnabled(True)

            ts = getattr(self.state, "materials_last_update", None)
            ts_txt = f"Updated: {ts}" if isinstance(ts, str) and ts.strip() else "Updated: (unknown)"
            cat_txt = ""
            try:
                if self.item_catalog.has_data():
                    lu = getattr(self.item_catalog, "last_updated", None)
                    lu_txt = f", updated {lu}" if isinstance(lu, str) and lu.strip() else ""
                    cat_txt = f" | Catalog: {self.item_catalog.count()}{lu_txt}"
            except Exception:
                cat_txt = ""
            summary = f"{ts_txt} | Items: {len(src)} | Low (≤{low_threshold}): {low} | Zero: {zero}{cat_txt}"
            self.inv_summary.setText(summary)
        except Exception:
            try:
                self.inv_summary.setText("")
                self.inv_table.setRowCount(0)
            except Exception:
                pass

    def _refresh_intel(self):
        # External intel (POIs) + Farming locations (both advisory, offline)
        pois = getattr(self.state, "external_pois", None) or []
        sys_name = getattr(self.state, "system", None) or ""
        farms = self.farming_locations.get_for_system(sys_name) if sys_name else []

        lines = []
        poi_count = 0
        farm_count = 0

        # POIs
        if isinstance(pois, list) and pois:
            poi_count = len(pois)
            lines.append("External POIs (advisory)")
            for rec in pois:
                if not isinstance(rec, dict):
                    continue
                title = rec.get("title") or rec.get("name") or "POI"
                cat = rec.get("category") or ""
                body = rec.get("body") or ""
                note = rec.get("note") or rec.get("description") or ""
                src = rec.get("source") or ""
                bits = []
                if cat:
                    bits.append(f"[{cat}]")
                bits.append(str(title))
                if body:
                    bits.append(f"— {body}")
                if note:
                    bits.append(f"— {note}")
                if src:
                    bits.append(f"(src: {src})")
                lines.append(" ".join(bits))

        # Farming locations
        if isinstance(farms, list) and farms:
            farm_count = len(farms)
            if lines:
                lines.append("")
            lu = getattr(self.farming_locations, "last_updated", None)
            lu_txt = f" (updated: {lu})" if isinstance(lu, str) and lu.strip() else ""
            lines.append(f"Farming locations in-system (advisory){lu_txt}")
            for rec in farms:
                if not isinstance(rec, dict):
                    continue
                dom = rec.get("domain") or ""
                name = rec.get("name") or "Farm Site"
                body = rec.get("body") or ""
                method = rec.get("method") or ""
                mats = rec.get("key_materials") or []
                if not isinstance(mats, list):
                    mats = []
                mats_txt = ", ".join([str(x) for x in mats[:6] if isinstance(x, str) and x.strip()])
                tail = "…" if len(mats) > 6 else ""
                bits = []
                if dom:
                    bits.append(f"[{dom}]")
                bits.append(str(name))
                if body:
                    bits.append(f"— {body}")
                if method:
                    bits.append(f"— {method}")
                if mats_txt:
                    bits.append(f"— Mats: {mats_txt}{tail}")
                lines.append(" ".join(bits))

        # Summary + fallback text
        if poi_count == 0 and farm_count == 0:
            self.intel_summary.setText("No offline intel for this system.")
            self.intel_box.setPlainText(
                "Optional files:\n"
                " - settings/external_pois.json (system POIs)\n"
                " - settings/elite_farming_locations.json (farming locations)\n"
            )
            return

        bits = []
        if poi_count:
            bits.append(f"{poi_count} external POIs")
        if farm_count:
            bits.append(f"{farm_count} farming locations")
        self.intel_summary.setText(f"{' | '.join(bits)} for this system (advisory only).")
        self.intel_box.setPlainText("\n".join(lines).strip() or "No usable intel entries.")

    def _refresh_combat(self):
        try:
            contacts = getattr(self.state, "combat_contacts", None) or {}
            cur_key = getattr(self.state, "combat_current_key", "") or ""

            rows = []
            for k, rec in contacts.items():
                if not isinstance(rec, dict):
                    continue
                rows.append((k, rec))

            # newest first (by timestamp string if present)
            def _ts(rec):
                ts = rec.get("LastSeen") or ""
                return ts if isinstance(ts, str) else ""
            rows.sort(key=lambda x: _ts(x[1]), reverse=True)

            self.combat_table.setSortingEnabled(False)
            self.combat_table.setRowCount(len(rows))

            selected_row = None
            for r, (k, rec) in enumerate(rows):
                pilot = rec.get("Pilot") or ""
                rank = rec.get("Rank") or ""
                ship = rec.get("Ship") or ""
                faction = rec.get("Faction") or ""
                power = rec.get("Power") or ""
                wanted = "Wanted" if rec.get("Wanted") else ""
                bounty = rec.get("Bounty")
                bounty_txt = f"{bounty:,}" if isinstance(bounty, int) else ""
                ts = rec.get("LastSeen") or ""
                if isinstance(ts, str) and "T" in ts:
                    # 2026-01-18T15:57:17Z -> 15:57:17
                    last_seen = ts.split("T", 1)[1].replace("Z", "")[:8]
                else:
                    last_seen = str(ts) if ts else ""

                it0 = QTableWidgetItem(str(pilot))
                it0.setData(Qt.ItemDataRole.UserRole, k)
                self.combat_table.setItem(r, 0, it0)
                self.combat_table.setItem(r, 1, QTableWidgetItem(str(rank)))
                self.combat_table.setItem(r, 2, QTableWidgetItem(str(ship)))
                self.combat_table.setItem(r, 3, QTableWidgetItem(str(faction)))
                self.combat_table.setItem(r, 4, QTableWidgetItem(str(power)))
                self.combat_table.setItem(r, 5, QTableWidgetItem(str(wanted)))
                self.combat_table.setItem(r, 6, QTableWidgetItem(str(bounty_txt)))
                self.combat_table.setItem(r, 7, QTableWidgetItem(str(last_seen)))

                if cur_key and k == cur_key:
                    selected_row = r

            self.combat_table.setSortingEnabled(True)

            if selected_row is not None:
                self.combat_table.selectRow(selected_row)
        except Exception:
            pass

    def _refresh_powerplay(self):
        # Everything here is journal-driven. Use getattr defensively to avoid crashes.
        pledged = getattr(self.state, "pp_power", None)
        pr = getattr(self.state, "pp_rank", None)
        me = getattr(self.state, "pp_merits", None)

        ctrl = getattr(self.state, "system_controlling_power", None)
        pp_state = getattr(self.state, "system_powerplay_state", None)
        powers = getattr(self.state, "system_powers", None) or []
        prog = getattr(self.state, "system_powerplay_conflict_progress", None) or {}

        if not pledged:
            self.pp_summary.setText("Not pledged to a Power. (PowerPlay details are hidden when not pledged.)")
            self.pp_actions.setText("")
            self.pp_progress.setRowCount(0)
            return

        pr_txt = pr if pr is not None else "?"
        me_txt = f"{me:,}" if isinstance(me, int) else "?"
        sysn = getattr(self.state, "system", None) or "Unknown system"

        bits = [f"System: {sysn}", f"Pledged: {pledged} (R{pr_txt} M{me_txt})"]
        # Relationship badge (simple, at-a-glance)
        friendly = bool(ctrl and ctrl == pledged)
        enemy = bool(ctrl and ctrl != pledged)
        if friendly:
            rel = "🟢 Friendly"
        elif enemy:
            rel = "🔴 Enemy"
        else:
            rel = "🟡 Neutral"

        bits = [rel, f"System: {sysn}", f"Pledged: {pledged} (R{pr_txt} M{me_txt})"]
        if ctrl:
            bits.append(f"Controlling Power: {ctrl}")
        if pp_state:
            bits.append(f"PowerPlay State: {pp_state}")
        if isinstance(powers, list) and powers:
            bits.append("Powers present: " + ", ".join([p for p in powers if isinstance(p, str)]))
        self.pp_summary.setText(" | ".join(bits))

        # Action hint (short, generic, and honest)
        s = str(pp_state or "").strip().lower()
        action = self._derive_pp_action(pledged, ctrl, pp_state, powers)

        self.pp_actions.setText(f"Recommended: {action}" if action else "")

        # Conflict progress table (if present)
        rows = []
        if isinstance(prog, dict):
            for p, v in prog.items():
                if isinstance(p, str) and isinstance(v, (int, float)):
                    rows.append((p, float(v)))
        rows.sort(key=lambda x: x[1], reverse=True)

        shown = rows[:12]
        self.pp_progress.setRowCount(len(shown))
        for r, (p, v) in enumerate(shown):
            self.pp_progress.setItem(r, 0, QTableWidgetItem(p))
            self.pp_progress.setItem(r, 1, QTableWidgetItem(f"{v*100:.2f}%"))

    def _refresh_exobiology(self):
        # Ensure FSS-only bio targets show even if handler refactors update
        # state.bio_signals without creating/updating the corresponding body record.
        try:
            if not isinstance(self.state.bodies, dict):
                self.state.bodies = {}

            bio_map = getattr(self.state, "bio_signals", {}) or {}
            genus_map = getattr(self.state, "bio_genuses", {}) or {}
            geo_map = getattr(self.state, "geo_signals", {}) or {}

            for body_name, bio_cnt in bio_map.items():
                if not isinstance(body_name, str) or not body_name.strip():
                    continue
                rec = self.state.bodies.get(body_name)
                if not isinstance(rec, dict):
                    rec = {"BodyName": body_name, "BodyID": None}
                if isinstance(bio_cnt, int):
                    rec["BioSignals"] = bio_cnt
                if body_name in genus_map:
                    rec["BioGenuses"] = genus_map.get(body_name, []) or []
                if body_name in geo_map:
                    rec["GeoSignals"] = geo_map.get(body_name, 0) or 0
                self.state.bodies[body_name] = rec
        except Exception:
            pass

        # Show Exobiology targets as soon as BioSignals exist (FSS), even before ScanOrganic.
        has_bio_targets = False
        for _b, _rec in (self.state.bodies or {}).items():
            if not isinstance(_rec, dict):
                continue
            bio = _rec.get("BioSignals", 0) or 0
            if isinstance(bio, int) and bio > 0:
                has_bio_targets = True
                break

        if not self.state.exo and not has_bio_targets:
            self.exo_table.setRowCount(0)
            self.exo_action.setText("🔬 Exobiology: no biological signals detected in this system yet.")
            self.exo_hint.setText("Tip: Use FSS to find Biological signals, then DSS a planet to reveal genus.")
            return

        rows = []
        try:
            exo_m = int(getattr(self.cfg, "exo_high_value_m", 2) or 2)
        except Exception:
            exo_m = 2
        exo_min = exo_m * 1_000_000
        try:
            self.exo_min_label.setText(f"{exo_m}M")
        except Exception:
            pass

        active = 0
        complete = 0
        high_value = 0
        targets = 0
        scanned_species = 0

        # Genus -> max known base value (from exo_values.json)
        genus_max = {}
        try:
            if self.exo_values:
                for _rec in self.exo_values.by_species.values():
                    g = getattr(_rec, "genus", None)
                    bv = getattr(_rec, "base_value", None)
                    if isinstance(g, str) and g.strip() and isinstance(bv, int):
                        gg = g.strip()
                        genus_max[gg] = max(int(genus_max.get(gg, 0) or 0), int(bv))
        except Exception:
            genus_max = {}

        def _norm_text(v):
            try:
                return " ".join(str(v).split())
            except Exception:
                return ""

        def _variant_color(v):
            """
            Normalize "Variant" display to the short color/name part.
            Examples:
            "Stratum Tectonicas - Green" -> "Green"
            "Bacterium Cerbrus - Teal"   -> "Teal"
            "Teal"                       -> "Teal"
            """
            if not isinstance(v, str):
                return ""
            s = _norm_text(v)
            if not s:
                return ""
            if " - " in s:
                try:
                    return s.split(" - ", 1)[1].strip()
                except Exception:
                    return s
            return s

        # Normalized body-name lookup to make Codex/DSS matching resilient to whitespace/name variants.
        body_key_by_norm = {}
        try:
            for _bn in (self.state.bodies or {}).keys():
                nk = _norm_text(_bn)
                if nk and nk not in body_key_by_norm:
                    body_key_by_norm[nk] = _bn
        except Exception:
            body_key_by_norm = {}

        # BodyID -> body-name key/record lookup to keep Exobiology matching reliable even if body_id_to_name is missing.
        body_key_by_id = {}
        body_rec_by_id = {}
        try:
            for _bn, _br in (self.state.bodies or {}).items():
                if not isinstance(_br, dict):
                    continue
                bid = _br.get("BodyID")
                if isinstance(bid, int) and bid not in body_key_by_id:
                    body_key_by_id[bid] = _bn
                    body_rec_by_id[bid] = _br
        except Exception:
            body_key_by_id = {}
            body_rec_by_id = {}

        # Track which (body, genus) already has a real ScanOrganic record so we can still show remaining DSS genuses.
        real_body_genus_name = set()  # (BodyName, Genus)
        real_body_genus_id = set()    # (BodyID, Genus)
 
        # Track which (body, genus) is already present via CODEX so we can suppress
        # CODEX duplicates when we already have a better "real" row (ScanOrganic) or DSS target row.
        # We track both BodyID and normalized BodyName keys for robustness.
        codex_body_genus_id = set()    # (BodyID, Genus)
        codex_body_genus_name = set()  # (BodyNameNorm, Genus)

        # Track which (body, genus) already has a row emitted (real ScanOrganic OR DSS target).
        # Used to suppress CODEX duplicates when we already have a better row to show.
        listed_body_genus_name = set()  # (BodyName, Genus)
        listed_body_genus_id = set()    # (BodyID, Genus)
        # CODEX hints: allow DSS genus rows to show Species/BaseValue without adding a duplicate CODEX row.
        codex_hint_name = {}            # (BodyName, Genus) -> Species text
        codex_hint_id = {}              # (BodyID, Genus) -> Species text
        codex_hint_var_name = {}        # (BodyName, Genus) -> Variant short text
        codex_hint_var_id = {}          # (BodyID, Genus) -> Variant short text
        codex_hint_base_name = {}       # (BodyName, Genus) -> Base value (int)
        codex_hint_base_id = {}         # (BodyID, Genus) -> Base value (int)
        codex_pending = []              # list of (body_txt, rec)

        for key, rec in (self.state.exo or {}).items():
            body_id = rec.get("BodyID")
            body_name = None
            if isinstance(body_id, int):
                body_name = self.state.body_id_to_name.get(body_id) or body_key_by_id.get(body_id)
            body_txt = body_name or (f"Body {body_id}" if body_id is not None else "Unknown Body")

            genus = rec.get("Genus", "")
            species = rec.get("Species", "")
            samples = int(rec.get("Samples", 0) or 0)
            last = (rec.get("LastScanType") or "").upper()
            if last == "CODEX":
                # CODEX hint: store species text so DSS rows can display it, but don't emit a row yet.
                gk = str(genus or "").strip()
                if not gk:
                    continue
                bn = _norm_text(body_name or body_txt)
                sp = species or rec.get("CodexName") or ""
                try:
                    sp = str(sp).strip()
                except Exception:
                    sp = ""
                vv = _variant_color(rec.get("Variant") or rec.get("CodexName") or "")
                if isinstance(body_id, int):
                    codex_hint_id[(body_id, gk)] = sp
                    if vv:
                        codex_hint_var_id[(body_id, gk)] = vv
                    # Mark CODEX presence for (BodyID, Genus)
                    codex_body_genus_id.add((body_id, gk))
                if bn:
                    codex_hint_name[(bn, gk)] = sp
                    if vv:
                        codex_hint_var_name[(bn, gk)] = vv
                    # Mark CODEX presence for (BodyNameNorm, Genus)
                    codex_body_genus_name.add((bn, gk))

                # Also capture best-known base/potential value from the CODEX record for DSS rows.
                bv = rec.get("BaseValue")
                if not isinstance(bv, int):
                    bv = rec.get("PotentialValue")
                # Journal does not provide an exobio "base value" for CodexEntry; derive from exo_values.json.
                if not isinstance(bv, int):
                    nm = rec.get("CodexName") or rec.get("Species") or ""
                    if isinstance(nm, str) and nm.strip() and getattr(self, "exo_values", None):
                        key = nm.strip()
                        exo_rec = self.exo_values.by_species.get(key)
                        if exo_rec is None and " - " in key:
                            exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                        if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                            bv = exo_rec.base_value
                if isinstance(bv, int) and bv > 0:
                    if isinstance(body_id, int):
                        codex_hint_base_id[(body_id, gk)] = bv
                    if bn:
                        codex_hint_base_name[(bn, gk)] = bv
                codex_pending.append((body_txt, rec))
                continue
            else:
                status = "COMPLETE" if rec.get("Complete") else (last or "IN PROGRESS")

            pot_v = rec.get("PotentialValue")
            pot_txt = f"{pot_v:,} cr" if isinstance(pot_v, int) else ""
            base_v = rec.get("BaseValue")
            # Journal does not provide a numeric base value for ScanOrganic; derive from exo_values.json.
            if not isinstance(base_v, int):
                nm = rec.get("Variant") or rec.get("Species") or rec.get("CodexName") or ""
                if isinstance(nm, str) and nm.strip() and getattr(self, "exo_values", None):
                    key = nm.strip()
                    exo_rec = self.exo_values.by_species.get(key)
                    if exo_rec is None and " - " in key:
                        exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                    if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                        base_v = exo_rec.base_value
            base_txt = f"{base_v:,} cr" if isinstance(base_v, int) else ""

            prog_txt = f"{samples}/3" if status != "CODEX" else "0/3"
            var_txt = _variant_color(rec.get("Variant") or "")
            # CCR UI hint (only when we have a requirement + not complete)
            status_txt = str(status)
            try:
                if status != "COMPLETE":
                    req = rec.get("CCRRequiredM")
                    rem = rec.get("CCRRemainingM")
                    dist = rec.get("CCRDistanceM")
                    if isinstance(req, int) and req > 0:
                        if isinstance(rem, int) and rem > 0:
                            # Example: ACTIVE • CCR 120/500m (need 380m)
                            if isinstance(dist, int) and dist >= 0:
                                status_txt = f"{status} • CCR {dist}/{req}m (need {rem}m)"
                            else:
                                status_txt = f"{status} • CCR need {rem}m / {req}m"
                        else:
                            # No remaining => OK to sample
                            status_txt = f"{status} • CCR OK ({req}m)"
            except Exception:
                status_txt = str(status)

            rows.append((samples, status, body_txt, genus, species, var_txt, pot_txt, base_txt, prog_txt, status_txt))
            scanned_species += 1

            gk = str(genus or "").strip()
            if gk:
                if isinstance(body_id, int):
                    real_body_genus_id.add((body_id, gk))
                bn = _norm_text(body_name)
                if bn:
                    real_body_genus_name.add((bn, gk))
                if isinstance(body_id, int):
                    listed_body_genus_id.add((body_id, gk))
                if bn:
                    listed_body_genus_name.add((bn, gk))

            # Action counts (ignore CODEX placeholders for "active/complete")
            if status != "CODEX":
                active += 1
                if rec.get("Complete"):
                    complete += 1
                hv = None
                if isinstance(base_v, int):
                    hv = base_v
                elif isinstance(pot_v, int):
                    hv = pot_v
                if isinstance(hv, int) and hv >= exo_min:
                    high_value += 1

        # 2) Planet-level targets from FSS/DSS (BioSignals / BioGenuses), even before ScanOrganic exists
        for body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue
            bio = rec.get("BioSignals", 0) or 0
            if not isinstance(bio, int) or bio <= 0:
                continue
            body_id = rec.get("BodyID")

            gen = rec.get("BioGenuses", []) or []
            if isinstance(gen, list) and gen:
                # One row per DSS-confirmed genus that is NOT yet scanned on this body.
                for g in gen:
                    gk = str(g or "").strip()
                    if not gk:
                        continue

                    # If CODEX already identified species/variant for this genus, we do NOT hide the DSS row.
                    # Instead, we enrich the DSS row below (Species/Variant/BaseValue) and mark it as CODEX.

                    if (isinstance(body_id, int) and (body_id, gk) in real_body_genus_id) or ((_norm_text(body), gk) in real_body_genus_name):
                        continue
                    pot = genus_max.get(gk)
                    pot_txt = f"{pot:,} cr" if isinstance(pot, int) and pot > 0 else ""
                    sp = ""
                    vv = ""
                    try:
                        if isinstance(body_id, int):
                            sp = codex_hint_id.get((body_id, gk), "") or ""
                            vv = codex_hint_var_id.get((body_id, gk), "") or ""
                        if not sp:
                            sp = codex_hint_name.get((_norm_text(body), gk), "") or ""
                        if not vv:
                            vv = codex_hint_var_name.get((_norm_text(body), gk), "") or ""
                    except Exception:
                        sp = ""
                        vv = ""
                    try:
                        sp = str(sp or "").strip()
                    except Exception:
                        sp = ""
                    try:
                        vv = str(vv or "").strip()
                    except Exception:
                        vv = ""
                    status_txt = "CODEX" if sp else "UNSCANNED"
                    base_txt = ""
                    try:
                        bv = None
                        if isinstance(body_id, int):
                            bv = codex_hint_base_id.get((body_id, gk))
                        if not isinstance(bv, int):
                            bv = codex_hint_base_name.get((_norm_text(body), gk))
                        # If we only know the species name (from Codex hint), derive base from exo_values.json.
                        if not isinstance(bv, int) and sp and getattr(self, "exo_values", None):
                            key = sp
                            exo_rec = self.exo_values.by_species.get(key)
                            if exo_rec is None and " - " in key:
                                exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                            if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                                bv = exo_rec.base_value
                        if isinstance(bv, int) and bv > 0:
                            base_txt = f"{bv:,} cr"
                    except Exception:
                        base_txt = ""
                    rows.append((0, status_txt, body, gk, sp, vv, pot_txt, base_txt, "0/3", status_txt))
                    targets += 1
                    if isinstance(pot, int) and pot >= exo_min:
                        high_value += 1
                    if isinstance(body_id, int):
                        listed_body_genus_id.add((body_id, gk))
                    if isinstance(body, str) and body.strip():
                        listed_body_genus_name.add((_norm_text(body), gk))
            else:
                # We know there are bio signals, but genus is unknown until DSS mapping reveals it.
                genus_txt = f"{bio} bio signals"
                status_txt = f"NEEDS DSS (Bio: {bio})"
                rows.append((0, status_txt, body, genus_txt, "", "", "", "", "0/3", status_txt))
                targets += 1

        # 3) Add CODEX placeholders only if no real ScanOrganic exists AND we did not already emit a DSS row for that genus.
        # NOTE: This MUST run after the DSS target rows above, otherwise we create duplicate "UNSCANNED" + "CODEX" rows.
        seen_codex = set()  # (body_key, genus)
        for body_txt, rec in (codex_pending or []):
            body_id = rec.get("BodyID")
            genus = str(rec.get("Genus", "") or "").strip()
            if not genus:
                continue
            body_name = None
            if isinstance(body_id, int):
                body_name = self.state.body_id_to_name.get(body_id) or body_key_by_id.get(body_id)
            body_key = body_id if isinstance(body_id, int) else (
                body_name.strip() if isinstance(body_name, str) and body_name.strip() else body_txt
            )
            dk = (body_key, genus)
            if dk in seen_codex:
                continue
            seen_codex.add(dk)

            # Strong suppression: if DSS already revealed this genus for this body, never emit a CODEX placeholder row.
            try:
                br = None
                if isinstance(body_id, int):
                    br = body_rec_by_id.get(body_id)
                bn = _norm_text(body_name or body_txt)
                if bn and bn in body_key_by_norm:
                    br = (self.state.bodies or {}).get(body_key_by_norm.get(bn))
                if br is None and isinstance(body_name, str) and body_name.strip():
                    br = (self.state.bodies or {}).get(body_name.strip())
                if br is None:
                    br = (self.state.bodies or {}).get(body_txt)
                if isinstance(br, dict):
                    dss_gen = br.get("BioGenuses", []) or []
                    if isinstance(dss_gen, list) and any(str(x or "").strip() == genus for x in dss_gen):
                        continue
            except Exception:
                pass

            # If we already have a better row (real ScanOrganic or DSS target), do not add a duplicate CODEX row.
            if (isinstance(body_id, int) and (body_id, genus) in listed_body_genus_id) or (
                (_norm_text(body_name or body_txt), genus) in listed_body_genus_name
            ):
                continue
            if (isinstance(body_id, int) and (body_id, genus) in real_body_genus_id) or (
                (_norm_text(body_name or body_txt), genus) in real_body_genus_name
            ):
                continue

            # Potential value is a DSS/genus concept; CODEX placeholders should not display it.
            pot_txt = ""
            base_v = rec.get("BaseValue")
            if not isinstance(base_v, int) and getattr(self, "exo_values", None):
                nm = rec.get("CodexName") or rec.get("Species") or ""
                if isinstance(nm, str) and nm.strip():
                    key = nm.strip()
                    exo_rec = self.exo_values.by_species.get(key)
                    if exo_rec is None and " - " in key:
                        exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                    if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                        base_v = exo_rec.base_value
            base_txt = f"{base_v:,} cr" if isinstance(base_v, int) else ""
            species_txt = rec.get("Species") or rec.get("CodexName") or ""
            if not isinstance(species_txt, str):
                species_txt = ""
            var_txt = _variant_color(rec.get("Variant") or rec.get("CodexName") or "")
            rows.append((0, "CODEX", body_txt, genus, species_txt.strip(), var_txt, pot_txt, base_txt, "0/3", "CODEX"))

        # Sort: actionable first. CODEX (species known, 0/3) should sit near UNSCANNED, not down with placeholders.
        def _status_rank(s):
            if not isinstance(s, str):
                return 99
            if s == "COMPLETE":
                return 50
            if s.startswith("NEEDS DSS"):
                return 10
            if s == "UNSCANNED":
                return 20
            if s == "CODEX":
                return 25
            return 30

        rows.sort(key=lambda x: (_status_rank(x[1]), -x[0]))

        shown = rows[:80]
        self.exo_table.setRowCount(len(shown))
        for r, (_samples, _status, body_txt, genus, species, var_txt, pot_txt, base_txt, prog_txt, status_txt) in enumerate(shown):
            self.exo_table.setItem(r, 0, QTableWidgetItem(str(body_txt)))
            self.exo_table.setItem(r, 1, QTableWidgetItem(str(genus)))
            self.exo_table.setItem(r, 2, QTableWidgetItem(str(species)))
            self.exo_table.setItem(r, 3, QTableWidgetItem(str(var_txt)))
            self.exo_table.setItem(r, 4, QTableWidgetItem(str(pot_txt)))
            self.exo_table.setItem(r, 5, QTableWidgetItem(str(base_txt)))
            self.exo_table.setItem(r, 6, QTableWidgetItem(str(prog_txt)))
            self.exo_table.setItem(r, 7, QTableWidgetItem(str(status_txt)))

        if has_bio_targets:
            self.exo_action.setText(
                f"🔬 Exobiology: {targets} targets • {scanned_species} scanned • {complete} complete • {high_value} high-value (≥ {exo_m}M)"
            )
            if not self.state.exo:
                self.exo_hint.setText("Biological signals detected. DSS a body to reveal genus; land to start samples.")
        else:
            self.exo_action.setText(f"🔬 Exobiology: {active} active • {complete} complete • {high_value} high-value (≥ {exo_m}M)")

    def _refresh_exploration(self):
        min_100k = int(getattr(self.cfg, "min_planet_value_100k", 10) or 10)
        if min_100k < 0:
            min_100k = 0
        min_value = min_100k * 100_000
        # Display as "x.yM" (0.1M steps)
        self.min_value_label.setText(f"{min_100k / 10:.1f}M")

        # Show valuable bodies based on current Scan data
        if not self.state.bodies:
            hint = "No scan data yet. Tip: Do FSS / honk / nav beacon so Scan events appear."
            if not self.planet_values:
                hint += " (planet_values.json not loaded — copy it to .ed_companion or next to main.py)"
            self.exploration_table.setRowCount(0)
            self.exploration_action.setText("🌍 Exploration: no bodies resolved in this system yet.")
            self.exploration_hint.setText(hint)
            return

        rows = []  # (sort_val, body, class, ls_txt, bio_txt, geo_txt, genera_txt, value_txt, tags_txt)
        best_below = None  # (value, line)
        bio_bodies = 0
        geo_bodies = 0
        tf_unmapped = 0
        hv_unmapped = 0
        for body, rec in self.state.bodies.items():
            est = rec.get("EstimatedValue")
            dist = rec.get("DistanceLS")
            pc = rec.get("PlanetClass") or ""
            # Normalize Frontier token-ish planet class strings for display
            pc_disp = self._norm_token(pc) or fmt.text(pc, default="")
            tf = rec.get("Terraformable", False)
            mapped = rec.get("Mapped", False)
            first = rec.get("FirstDiscovered", False)
            bio = rec.get("BioSignals", 0) or 0
            geo = rec.get("GeoSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []
            if isinstance(bio, int) and bio > 0:
                bio_bodies += 1
            if isinstance(geo, int) and geo > 0:
                geo_bodies += 1
            if tf and not mapped:
                tf_unmapped += 1
            if isinstance(est, int) and est >= min_value and not mapped:
                hv_unmapped += 1

            # Sort key: estimated value if present else 0
            sort_val = int(est) if isinstance(est, int) else 0

            # Track best candidate even if it doesn't pass the filter
            if isinstance(est, int):
                preview_tags = []
                if tf:
                    preview_tags.append("Terraformable")
                if first:
                    preview_tags.append("NEW")
                if mapped:
                    preview_tags.append("Mapped")
                else:
                    preview_tags.append("UNMAPPED")
                dist_txt = (fmt.int_commas(dist) + " LS") if isinstance(dist, (float, int)) else ""
                est_txt = fmt.credits(est, default="?")
                tag_txt = (" [" + ", ".join(preview_tags) + "]") if preview_tags else ""
                preview_line = f"{body} — {pc_disp} — {dist_txt} — {est_txt}{tag_txt}".strip()
                if (best_below is None) or (est > best_below[0]):
                    best_below = (est, preview_line)

            # Filter: Exploration tab shows high-value bodies AND any bodies with Geological signals
            # (Geological is useful for raw-material farming, even when the body is not valuable for credits.)
            include_value = isinstance(est, int) and est >= min_value
            include_geo = isinstance(geo, int) and geo > 0
            if not include_value and not include_geo:
                continue

            tags = []
            if tf:
                tags.append("Terraformable")
            if first:
                tags.append("NEW")
            if mapped:
                tags.append("Mapped")
            else:
                tags.append("UNMAPPED")

            dist_txt = (fmt.int_commas(dist) + " LS") if isinstance(dist, (float, int)) else ""
            est_txt = fmt.credits(est, default="?") if isinstance(est, int) else "?"
            tags_txt = ", ".join(tags) if tags else ""
            bio_txt = str(bio) if isinstance(bio, int) and bio > 0 else ""
            geo_txt = str(geo) if isinstance(geo, int) and geo > 0 else ""
            genera_txt = ", ".join([fmt.text(x, default="") for x in gen if fmt.text(x, default="")]) if isinstance(gen, list) and gen else ""
            rows.append((sort_val, fmt.text(body, default=""), pc_disp, dist_txt, bio_txt, geo_txt, genera_txt, est_txt, tags_txt))

        rows.sort(key=lambda x: x[0], reverse=True)

        scanned = len(self.state.bodies)
        total = self.state.system_body_count
        header_bits = []
        if isinstance(total, int) and total > 0:
            remaining = max(0, total - scanned)
            header_bits.append(f"Bodies resolved: {scanned}/{total} (unknown remaining: {remaining})")
        else:
            header_bits.append(f"Bodies resolved: {scanned} (honk for total count)")
        if not self.planet_values:
            header_bits.append("WARNING: planet_values.json not loaded")
        header_bits.append(f"Showing bodies worth ≥ {fmt.credits(min_value, default='?')} or with Geo signals")
        nb = getattr(self.state, "non_body_count", None)
        if isinstance(nb, int) and nb > 0:
            header_bits.append(f"Non-body signals: {nb} (FSS)")
        sigs = getattr(self.state, "system_signals", None) or []
        if isinstance(sigs, list) and sigs:
            header_bits.append(f"Signals discovered: {len(sigs)}")

        # Fill table (top 50 is plenty)
        shown = rows[:50]
        self.exploration_table.setRowCount(len(shown))
        for r, (_sv, b, pc, ls_txt, bio_txt, geo_txt, genera_txt, v_txt, tags_txt) in enumerate(shown):
            self.exploration_table.setItem(r, 0, QTableWidgetItem(str(b)))
            self.exploration_table.setItem(r, 1, QTableWidgetItem(str(pc)))
            # Ensure numeric sorting on the "LS" column (avoid lexicographic sort like "100" < "9")
            it_ls = QTableWidgetItem(str(ls_txt))
            try:
                s = str(ls_txt).replace("LS", "").strip()
                # Keep only digits/dot/minus (robust against "12,345 LS")
                s = s.replace(",", "")
                v = float(s) if s else None
                if v is not None:
                    it_ls.setData(Qt.ItemDataRole.UserRole, v)
            except Exception:
                pass
            self.exploration_table.setItem(r, 2, it_ls)
            self.exploration_table.setItem(r, 3, QTableWidgetItem(str(bio_txt)))
            self.exploration_table.setItem(r, 4, QTableWidgetItem(str(geo_txt)))
            self.exploration_table.setItem(r, 5, QTableWidgetItem(str(genera_txt)))
            it_val = QTableWidgetItem(str(v_txt))

            # Numeric sort key: use the stored sort value directly
            try:
                it_val.setData(Qt.ItemDataRole.UserRole, int(_sv))
            except Exception:
                pass
            self.exploration_table.setItem(r, 6, it_val)
            self.exploration_table.setItem(r, 7, QTableWidgetItem(str(tags_txt)))

        # Hint line under the table
        if not shown:
            hint = "No bodies above threshold (or with Geo signals) yet. Tip: lower the slider, or scan more bodies (FSS/nav beacon)."
            if best_below:
                hint += f"\nBest found so far (below threshold): {best_below[1]}"
            self.exploration_hint.setText("\n".join(header_bits) + "\n" + hint)
        else:
            self.exploration_hint.setText("\n".join(header_bits))

        self.exploration_action.setText(
            f"🌍 Exploration: {len(shown)} shown • {bio_bodies} bodies with bio • {geo_bodies} bodies with geo • {tf_unmapped} TF unmapped • {hv_unmapped} high-value unmapped"
        )

        # System signals box (FSSSignalDiscovered)
        try:
            sigs = getattr(self.state, "system_signals", None) or []
            if isinstance(sigs, list) and sigs:
                out_lines = []

                # Categorize
                cat_order = ["Phenomena", "Megaship", "Station", "USS", "Other"]
                cats = {k: [] for k in cat_order}
                cat_counts = {k: 0 for k in cat_order}
                uss_counts = {}
                for s in sigs:
                    if not isinstance(s, dict):
                        continue
                    cat_raw = s.get("Category") if isinstance(s.get("Category"), str) else "Other"
                    cat = self._norm_token(cat_raw) or "Other"
                    if cat not in cats:
                        cat = "Other"
                    cats[cat].append(s)
                    cat_counts[cat] += 1
                    if cat == "USS":
                        u = self._norm_token(s.get("USSType") or "")
                        if u:
                            uss_counts[u] = uss_counts.get(u, 0) + 1

                # Summary line (low noise)
                out_lines.append(
                    "Summary: "
                    + " | ".join([f"{k} x{cat_counts[k]}" for k in cat_order if cat_counts.get(k, 0)])
                )

                # Optional USS breakdown (still compact)
                if uss_counts:
                    bits = []
                    for k, v in sorted(uss_counts.items(), key=lambda x: (-x[1], str(x[0]).lower()))[:8]:
                        bits.append(f"{k} x{v}")
                    out_lines.append("USS types: " + " | ".join(bits))

                out_lines.append("")

                # Detailed list (capped)
                max_lines = 30
                used = 0
                for cat in cat_order:
                    if not cats[cat]:
                        continue
                    out_lines.append(f"{cat}:")
                    for s in cats[cat]:
                        if used >= max_lines:
                            break
                        nm = self._norm_token(s.get("SignalName") or "Signal") or "Signal"
                        stype = self._norm_token(s.get("SignalType") or "")
                        uss = self._norm_token(s.get("USSType") or "")
                        tl = s.get("ThreatLevel")
                        tr = s.get("TimeRemaining")
                        bits = [str(nm)]
                        if cat == "USS" and uss:
                            bits.append(f"({uss})")
                        if cat == "Other" and stype:
                            bits.append(f"[{stype}]")
                        if isinstance(tl, int):
                            bits.append(f"Threat {tl}")
                        if isinstance(tr, (int, float)):
                            bits.append(f"TR {int(tr)}s")
                        out_lines.append(" | ".join(bits))
                        used += 1
                    out_lines.append("")
                    if used >= max_lines:
                        break

                self.system_signals_box.setPlainText("\n".join(out_lines).strip())
            else:
                nb = getattr(self.state, "non_body_count", None)
                if isinstance(nb, int) and nb > 0:
                    self.system_signals_box.setPlainText(f"{nb} non-body signals present. Use FSS to discover details.")
                else:
                    self.system_signals_box.setPlainText("")
        except Exception:
            self.system_signals_box.setPlainText("")

        self._refresh_materials_shortlist()

    def _refresh_materials_shortlist(self):
        """
        Ranks landable bodies with Geo signals for raw-material farming.
        Uses Scan-derived fields when available: Landable, Volcanism, Materials.
        """
        try:
            rare = {
                "polonium", "tellurium", "ruthenium", "yttrium", "antimony",
                "arsenic", "selenium", "zirconium", "niobium", "tin",
                "molybdenum", "technetium",
            }

            # Needs set (raw mats): low inventory threshold
            low_threshold = 25
            low_raw = set()
            inv_raw = getattr(self.state, "materials_raw", {}) or {}
            if isinstance(inv_raw, dict):
                for k, v in inv_raw.items():
                    if isinstance(k, str) and isinstance(v, int) and v <= low_threshold:
                        low_raw.add(k.strip().lower())

            need_raw = low_raw

            targets = []
            for body, rec in (self.state.bodies or {}).items():
                if not isinstance(rec, dict):
                    continue
                landable = rec.get("Landable")
                if landable is not True:
                    continue
                geo = rec.get("GeoSignals", 0) or 0
                if not (isinstance(geo, int) and geo > 0):
                    continue

                dist = rec.get("DistanceLS")
                dist_v = float(dist) if isinstance(dist, (int, float)) else None

                volcanism = rec.get("Volcanism") or ""
                volc_present = bool(
                    isinstance(volcanism, str)
                    and volcanism.strip()
                    and ("no volcanism" not in volcanism.strip().lower())
                )

                mats = rec.get("Materials") or {}
                if not isinstance(mats, dict):
                    mats = {}

                rare_score = 0.0
                need_score = 0.0
                for k, v in mats.items():
                    if not isinstance(v, (int, float)):
                        continue
                    nm = str(k).strip().lower()
                    if nm in rare:
                        rare_score += float(v)
                    if nm in need_raw:
                        need_score += float(v)

                # Score: Geo dominates, then volcanism, then "needed" mats, then rare mats, then distance.
                score = (
                    (geo * 1000)
                    + (120 if volc_present else 0)
                    + (need_score * 20.0)
                    + (rare_score * 8.0)
                    - ((dist_v or 0.0) * 0.10)
                )
                targets.append((score, body, geo, dist_v, volcanism, mats))

            targets.sort(key=lambda x: x[0], reverse=True)
            show = targets[:8]

            if not show:
                self.materials_box.setPlainText(
                    "No landable bodies with Geological signals yet.\n"
                    "Tip: resolve bodies (FSS/nav beacon) so Scan events populate Landable/Materials/Volcanism."
                )
                return

            out = []
            out.append("Ranked targets (landable + Geo):")
            out.append(f"(!) low inventory (≤{low_threshold}) | (*) rarer raw mats")
            out.append("")

            for i, (_score, body, geo, dist_v, volcanism, mats) in enumerate(show, 1):
                head = f"{i}. {body}"
                if isinstance(dist_v, float):
                    head += f" — {dist_v:.0f} LS"
                head += f" — Geo {geo}"
                if isinstance(volcanism, str) and volcanism.strip() and ("no volcanism" not in volcanism.lower()):
                    head += " — Volcanism"
                out.append(head)

                # Top materials by %
                items = []
                for k, v in mats.items():
                    if isinstance(v, (int, float)):
                        items.append((float(v), str(k)))
                items.sort(key=lambda x: x[0], reverse=True)

                if items:
                    parts = []
                    for pct, nm in items[:6]:
                        raw = (nm or "").strip()
                        if not raw:
                            continue
                        disp = raw.capitalize() if raw.islower() else raw
                        key = raw.strip().lower()
                        bang = "!" if key in need_raw else ""
                        star = "*" if key in rare else ""
                        parts.append(f"{disp}{bang}{star} {pct:.1f}%")
                    out.append("   " + " | ".join(parts))
                else:
                    out.append("   Materials: (not yet scanned)")

                if isinstance(volcanism, str) and volcanism.strip() and ("no volcanism" not in volcanism.lower()):
                    out.append(f"   Volcanism: {volcanism.strip()}")

            self.materials_box.setPlainText("\n".join(out).strip())
        except Exception:
            # Never break the UI refresh loop.
            self.materials_box.setPlainText("")

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
        if not self.state.system:
            self.system_card.setPlainText("No system data yet.")
            self.factions_table.setRowCount(0)
            return

        lines = []
        lines.append(f"System: {self.state.system}")
        if self.state.controlling_faction:
            lines.append(f"Controlling Faction: {self.state.controlling_faction}")

        meta = []
        allegiance = self._norm_token(getattr(self.state, "system_allegiance", None))
        government = self._norm_token(getattr(self.state, "system_government", None))
        security = self._norm_token(getattr(self.state, "system_security", None))
        economy = self._norm_token(getattr(self.state, "system_economy", None))
        population = fmt.int_commas(getattr(self.state, "population", None))

        if allegiance:
            meta.append(f"Allegiance: {allegiance}")
        if government:
            meta.append(f"Government: {government}")
        if security:
            meta.append(f"Security: {security}")
        if economy:
            meta.append(f"Economy: {economy}")
        if population:
            meta.append(f"Population: {population}")
        if meta:
            lines.append(" | ".join(meta))

        self.system_card.setPlainText("\n".join(lines))

        # Fill factions table (top 8 by influence)
        facs = []
        for f in (self.state.factions or []):
            if not isinstance(f, dict):
                continue
            name = f.get("Name", "Unknown")
            infl = f.get("Influence")
            infl_val = float(infl) if isinstance(infl, (float, int)) else -1.0
            infl_txt = fmt.pct_1(infl_val, default="?") if infl_val >= 0 else "?"

            state = ""
            states = f.get("ActiveStates") or []
            if isinstance(states, list) and states:
                st = states[0]
                if isinstance(st, dict):
                    # Prefer Localised label; otherwise normalize Frontier token-ish values
                    state = fmt.text(
                        st.get("State_Localised") or self._norm_token(st.get("State")) or st.get("State") or "",
                        default="",
                    )

            rep = f.get("MyReputation")

            # MyReputation is usually -1..+1; display as % if in 0..1 (or -1..1), else fallback numeric
            if isinstance(rep, (float, int)):
                rep_f = float(rep)
                if -1.0 <= rep_f <= 1.0:
                    # shift -1..+1 to -100..+100 for readability
                    rep_txt = f"{(rep_f * 100):.1f}%"
                else:
                    rep_txt = f"{rep_f:.1f}"
            else:
                rep_txt = ""

            facs.append((infl_val, str(name), infl_txt, state, rep_txt))

        facs.sort(key=lambda x: x[0], reverse=True)
        top = facs[:8]
        self.factions_table.setRowCount(len(top))
        for r, (_infl_val, name, infl_txt, state, rep_txt) in enumerate(top):
            self.factions_table.setItem(r, 0, QTableWidgetItem(name))
            self.factions_table.setItem(r, 1, QTableWidgetItem(infl_txt))
            self.factions_table.setItem(r, 2, QTableWidgetItem(state))
            self.factions_table.setItem(r, 3, QTableWidgetItem(rep_txt))

    def _compute_action_state(self):
        """
        Single authority for all 'Action:' decisions.
        Returns a dict with preformatted action strings or None.
        """
        out = {
            "exploration": None,
            "exobiology": [],
        }

        try:
            min_100k = int(getattr(self.cfg, "min_planet_value_100k", 10) or 10)
            if min_100k < 0:
                min_100k = 0
            min_value = min_100k * 100_000
            fss_value = max(300_000, int(min_value * 0.20))

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

        for _body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue

            est = rec.get("EstimatedValue")
            mapped = bool(rec.get("Mapped", False))
            tf = bool(rec.get("Terraformable", False))

            bio = rec.get("BioSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []

            if tf and not mapped:
                tf_unmapped += 1

            if isinstance(est, int) and est >= fss_value and not mapped:
                hv_unmapped += 1

            if isinstance(bio, int) and bio > 0 and not gen:
                bio_need_dss += 1

        if hv_unmapped > 0 or tf_unmapped > 0:
            out["exploration"] = (
                f"🌍 Action: {hv_unmapped} bodies worth mapping (FSS) | {tf_unmapped} TF unmapped"
            )

        if bio_need_dss > 0:
            out["exobiology"].append(
                f"🔬 Action: {bio_need_dss} bodies have bio signals — DSS/map to reveal genus"
            )

        dss_hv = 0
        for _body, rec in (self.state.bodies or {}).items():
            gen = rec.get("BioGenuses", []) or []
            for g in gen:
                if genus_max.get(g, 0) >= exo_min:
                    dss_hv += 1
                    break

        if dss_hv > 0:
            out["exobiology"].append(
                f"🔬 Action: {dss_hv} bodies with possible high-value exo genus (≥ {exo_m}M)"
            )

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
