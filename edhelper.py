import os
import json
import time
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer

import sys

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QTableWidget, QTableWidgetItem
)
from PyQt6.QtGui import QPalette, QColor

class StatusIndicator(QFrame):
    def __init__(self, text, color="#00eaff"):
        super().__init__()
        self.setFixedSize(14, 14)
        self.setStyleSheet(f"background-color: {color}; border-radius: 7px; border: 1px solid #444;")
        self.label = QLabel(text)
        self.label.setStyleSheet("color: #e0e8ff; font-size: 13px;")

class StatusRow(QWidget):
    def __init__(self, label_text, initial_value="", color="#00eaff"):
        super().__init__()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 2)
        self.indicator = StatusIndicator(label_text, color)
        self.value_label = QLabel(initial_value)
        self.value_label.setStyleSheet("color: #f0f4ff; font-size: 14px;")
        layout.addWidget(self.indicator)
        layout.addWidget(self.value_label)
        layout.addStretch()
        self.setLayout(layout)

    def set_value(self, text):
        self.value_label.setText(text)

class TabContent(QWidget):
    def __init__(self, title):
        super().__init__()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 22px; color: #00eaff; font-weight: bold;")
        self.layout.addWidget(title_label)
        self.rows = {}
        self.setLayout(self.layout)

    def add_row(self, key, label_text, initial_value="", color="#00eaff"):
        row = StatusRow(label_text, initial_value, color)
        self.layout.addWidget(row)
        self.rows[key] = row

    def update_row(self, key, value):
        if key in self.rows:
            self.rows[key].set_value(value)

class GameState(QObject):
    system_changed = pyqtSignal(str)
    security_changed = pyqtSignal(str)
    economy_changed = pyqtSignal(str)
    scanned_changed = pyqtSignal(str)
    high_value_changed = pyqtSignal(str)
    first_discovery_changed = pyqtSignal(str)
    power_changed = pyqtSignal(str)
    merits_changed = pyqtSignal(str)
    pledged_power_changed = pyqtSignal(str)
    system_pp_state_changed = pyqtSignal(str)
    controlling_faction_changed = pyqtSignal(str)
    faction_status_changed = pyqtSignal(str)
    system_info_changed = pyqtSignal(str)
    faction_reputation_changed = pyqtSignal(str)
    actions_changed = pyqtSignal(str)
    combat_changed = pyqtSignal(str)
    exobiology_changed = pyqtSignal(str)
    data_updated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.journal_path = self._find_latest_journal()
        self.last_position = 0
        self._last_modified = 0
        self.factions = []
        self.faction_reps = {}
        self.combat_bounties = 0
        self.scanned_text = ""

    def _find_latest_journal(self):
        saved_games = Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"
        if not saved_games.exists():
            return None
        journals = list(saved_games.glob("Journal.*.log"))
        if not journals:
            return None
        latest = max(journals, key=lambda p: p.stat().st_mtime)
        return str(latest)

    def check_journal(self):
        # Find latest journal file every time
        saved_games = Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"
        if not saved_games.exists():
            return

        journals = list(saved_games.glob("Journal.*.log"))
        if not journals:
            return

        latest_file = max(journals, key=lambda p: p.stat().st_mtime)
        latest_path = str(latest_file)

        # Switch file if changed
        if not hasattr(self, 'current_journal') or latest_path != self.current_journal:
            self.current_journal = latest_path
            self.last_position = 0
            print(f"New journal: {latest_file.name}")

        try:
            with open(self.current_journal, "r", encoding="utf-8") as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()

            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    self.process_event(event)
                except json.JSONDecodeError:
                    continue

        except Exception as e:
            print(f"Journal error: {e}")

    def process_event(self, event):
        evt = event.get("event")
        if not evt:
            return
        handler = self._get_handler(evt)
        if handler:
            handler(event)
        self._compute_actions()

    def _get_handler(self, event_type):
        handlers = {
            "Location": self._handle_location_info,
            "FSDJump": self._handle_location_info,
            "FSSDiscoveryScan": self._handle_fss_progress,
            "FSSAllBodiesFound": self._handle_fss_complete,
            "Scan": self._handle_body_scan,
            "SAAScanComplete": self._handle_dss_complete,
            "SAASignalsFound": self._handle_planet_signals,
            "Powerplay": self._handle_pledged_power,
            "PowerplayMerit": self._handle_powerplay_merit,
            "Bounty": self._handle_bounty,
            "Interdiction": self._handle_interdiction,
            "Interdicted": self._handle_interdicted,
            "UnderAttack": self._handle_under_attack,
            "ShipTargeted": self._handle_ship_targeted,
            "HeatWarning": self._handle_heat_warning,
            "HullDamage": self._handle_hull_damage,
            "ShieldState": self._handle_shield_state,
            "ScanOrganic": self._handle_scan_organic,
            "FactionReputationUpdate": self._handle_faction_reputation,
        }
        return handlers.get(event_type)

    def _handle_location_info(self, event):
        self.system_changed.emit(event.get("StarSystem", "Unknown"))
        sec = event.get("SystemSecurity", "?").replace("$SYSTEM_SECURITY_", "").replace("_", " ").title()
        econ1 = event.get("SystemEconomy", "?").replace("$economy_", "").replace("_", " ").title()
        econ2 = event.get("SystemSecondEconomy", "?").replace("$economy_", "").replace("_", " ").title()
        econ = f"{econ1} / {econ2}" if econ2 and econ2 != "?" else econ1
        gov  = event.get("SystemGovernment", "?").replace("$government_", "").replace("_", " ").title()
        pop  = f"{event.get('Population', 0):,}" if event.get('Population') else "?"
        self.system_info_changed.emit(f"{sec} • {econ} • {gov} • {pop}")
        sys_faction = event.get("SystemFaction", {})
        ctrl_state = sys_faction.get('FactionState', 'None').replace("$government_", "").replace("_", " ").title()
        ctrl = f"{sys_faction.get('Name','?')} ({ctrl_state})"
        self.controlling_faction_changed.emit(ctrl)
        pp_state = event.get("PowerplayState", "None")
        powers = event.get("Powers", [])
        if powers:
            ctrl_power = powers[0]
            hostiles = [p for p in powers[1:]]
            status = f"{pp_state}: {ctrl_power}"
            if hostiles: status += f" (hostile: {', '.join(hostiles)})"
            self.system_pp_state_changed.emit(status)
        else:
            self.system_pp_state_changed.emit(pp_state)
        self.factions = event.get("Factions", [])
        if self.factions:
            top = sorted(self.factions, key=lambda f: f.get("Influence",0), reverse=True)[:3]
            stat = " | ".join([
                f"{f['Name']}: {f['Influence']:.0%} ({f['FactionState'].replace('$government_', '').replace('_', ' ').title() or 'None'})"
                for f in top
            ])
            self.faction_status_changed.emit(stat)

    def _handle_fss_progress(self, event):
        percent = int(event.get("Progress", 0) * 100)
        bodies = event.get("BodyCount", "?")
        self.scanned_changed.emit(f"FSS: {percent}% • {bodies} bodies")

    def _handle_fss_complete(self, event):
        count = event.get("Count", "?")
        self.scanned_changed.emit(f"System complete • {count} bodies")

    def _handle_body_scan(self, event):
        name = event.get("BodyName", "Unknown")
        cls = event.get("PlanetClass") or event.get("StarType") or "?"
        if "Planet" in cls or "World" in cls:
            value = self._estimate_planet_value(event)
            line = f"{name} • {cls.replace(' body','')} • ~{value:,} cr"
            if not event.get("WasDiscovered", True): line += " • First"
            if not event.get("WasMapped", True): line += " • DSS needed"
            self.scanned_changed.emit(line)
            self.scanned_text = line
            if value > 100000:
                self.high_value_changed.emit(f"High value • {name} • {value:,} cr")

    def _handle_dss_complete(self, event):
        name = event.get("BodyName", "Unknown")
        self.scanned_changed.emit(f"DSS complete: {name} • 100%")
        parts = []
        if cls := event.get("PlanetClass", "").replace(" body", ""):
            parts.append(cls)
        if event.get("TerraformState"): parts.append("Terraformable")
        if atmo := event.get("AtmosphereType"):
            if atmo != "None": parts.append(atmo.replace("Atmosphere", "").strip())
        if volc := event.get("VolcanismType"): parts.append(volc)
        if parts:
            self.scanned_changed.emit(" • ".join(parts))

    def _handle_planet_signals(self, event):
        name = event.get("BodyName", "Unknown")
        signals = event.get("Signals", [])
        if not signals:
            return
        bios = mats = guardians = thargoids = humans = other = 0
        for s in signals:
            t = s.get("Type", "").lower()
            c = s.get("Count", 0)
            if "biological" in t or "biology" in t: bios += c
            elif any(x in t for x in ["geological","mineral","raw","manufactured"]): mats += c
            elif "guardian" in t: guardians += c
            elif "thargoid" in t or "barnacle" in t or "tharg" in t: thargoids += c
            elif any(x in t for x in ["human","settlement","installation","nav","beacon","wreck"]): humans += c
            else: other += c
        if any([bios, mats, guardians, thargoids, humans, other]):
            parts = []
            if bios: parts.append(f"Bio: {bios}")
            if mats: parts.append(f"Mats: {mats}")
            if guardians: parts.append(f"Guardian: {guardians}")
            if thargoids: parts.append(f"Thargoid: {thargoids}")
            if humans: parts.append(f"Human: {humans}")
            if other: parts.append(f"Other: {other}")
            self.scanned_changed.emit(f"{name} • {' • '.join(parts)}")

    def _handle_pledged_power(self, event):
        power = event.get("Power", "None")
        self.power_changed.emit(power)
        self.pledged_power_changed.emit(power)

    def _handle_powerplay_merit(self, event):
        self.merits_changed.emit(f"{event.get('Merits', 0)}")

    def _handle_bounty(self, event):
        reward = event.get("TotalReward", 0)
        if reward > 0:
            self.combat_bounties += reward
            self.combat_changed.emit(f"Bounties: {self.combat_bounties:,} cr")

    def _handle_interdiction(self, event):
        victim = event.get("Interdicted", "unknown")
        self.combat_changed.emit(f"Interdicting: {victim}")

    def _handle_interdicted(self, event):
        interdictor = event.get("Interdictor", "unknown")
        success = "success" if event.get("Success", False) else "failed"
        self.combat_changed.emit(f"Interdicted by {interdictor} – {success}")

    def _handle_under_attack(self, event):
        attacker = event.get("Attacker", "?")
        self.combat_changed.emit(f"Under attack – {attacker}")
        self.combat_status = "Under attack"

    def _handle_ship_targeted(self, event):
        target = event.get("TargetNameLocalized") or event.get("Ship", "?")
        status = event.get("TargetLocked", False)
        if status:
            self.combat_changed.emit(f"Target locked: {target}")
        else:
            self.combat_changed.emit("Target lost")

    def _handle_heat_warning(self, event):
        self.combat_changed.emit("Heat warning – reduce heat")

    def _handle_hull_damage(self, event):
        health = event.get("Health", 0)
        if health < 0.3:
            self.combat_changed.emit(f"Hull critical: {int(health*100)}%")

    def _handle_shield_state(self, event):
        shields_up = event.get("ShieldsUp", False)
        text = "Shields up" if shields_up else "Shields down"
        self.combat_changed.emit(text)

    def _handle_scan_organic(self, event):
        genus   = event.get("Genus_Localised")   or event.get("Genus",   "Unknown").replace("$Codex_", "").replace("_", " ").title()
        species = event.get("Species_Localised") or event.get("Species", "Unknown").replace("$Codex_", "").replace("_", " ").title()
        variant = event.get("Variant", "None")
        scan_type = event.get("ScanType", "Unknown")

        display = f"{genus} {species}"
        if variant and variant != "None":
            display += f" ({variant})"
        if scan_type != "Unknown":
            display += f" • {scan_type}"

        self.exobiology_changed.emit(display)

        display = f"{genus} {species}"
        if variant and variant != "None":
            display += f" ({variant})"
        if scan_type != "Unknown":
            display += f" • {scan_type}"

        self.exobiology_changed.emit(display)

    def _handle_faction_reputation(self, event):
        faction = event.get("Faction", "Unknown")
        rep = event.get("Reputation", 0)
        self.faction_reps[faction] = rep
        levels = []
        for f, r in sorted(self.faction_reps.items(), key=lambda x: x[1], reverse=True)[:3]:
            level = "Allied" if r >= 90 else "Cordial" if r >= 45 else "Friendly" if r >= 10 else "Neutral" if r >= -10 else "Unfriendly" if r >= -90 else "Hostile"
            levels.append(f"{f}: {level} ({r:+.0f})")
        self.faction_reputation_changed.emit("\n".join(levels))

    def _estimate_planet_value(self, event):
        base_values = {
            "Earthlike body": 250000, "Water world": 180000, "High metal content body": 120000,
            "Ammonia world": 100000, "Rocky icy body": 80000, "Icy body": 60000,
            "Rocky body": 50000, "Metal rich body": 150000, "Class I gas giant": 30000,
            "Class II gas giant": 80000, "Class III gas giant": 40000, "Class IV gas giant": 20000,
            "Class V gas giant": 10000,
        }
        planet_class = event.get("PlanetClass", "")
        base = base_values.get(planet_class, 20000)
        if event.get("TerraformState"): base *= 2.5
        if event.get("AtmosphereType") in ["EarthLike", "Water", "Ammonia"]: base *= 1.4
        if event.get("VolcanismType"): base *= 1.15
        mass = event.get("MassEM", 1.0)
        radius = event.get("Radius", 1.0) / 1000
        if 0.8 <= mass <= 1.5 and 0.8 <= radius <= 1.5: base *= 1.3
        return int(base)

    def _compute_actions(self):
        actions = []
        if hasattr(self, 'pledged_power') and self.pledged_power == "Zachary Hudson":
            actions.append({"action": "Fortify", "priority": "High", "target": "Current system"})
        if hasattr(self, 'system_pp_state') and "hostile" in self.system_pp_state.lower():
            actions.append({"action": "Undermine", "priority": "Medium", "target": "Enemy power"})
        if "DSS needed" in self.scanned_text:
            actions.append({"action": "Map planet", "priority": "High", "target": "High-value body"})
        if hasattr(self, 'combat_status') and self.combat_status == "Under attack":
            actions.append({"action": "Deploy hardpoints", "priority": "Critical", "target": "Attacker"})
        if hasattr(self, 'faction_status') and "War" in self.faction_status:
            actions.append({"action": "Join CZ", "priority": "High", "target": "Controlling faction"})
        ctrl_faction = next((f for f in self.factions if f.get("Controlling")), {})
        ctrl_states = ctrl_faction.get("PendingStates", []) + ctrl_faction.get("ActiveStates", [])
        if "Boom" in ctrl_states:
            actions.append({"action": "Trade missions", "priority": "High", "target": "Controlling faction"})
        if "War" in ctrl_states or "CivilWar" in ctrl_states:
            actions.append({"action": "CZ for ctrl faction", "priority": "High", "target": ctrl_faction.get("Name")})
        if "Election" in ctrl_states:
            actions.append({"action": "Missions/trade", "priority": "High", "target": ctrl_faction.get("Name")})
        if "Outbreak" in ctrl_states:
            actions.append({"action": "Med deliveries", "priority": "Medium", "target": "Clear outbreak"})
        if ctrl_faction.get("Influence", 0) < 75:
            actions.append({"action": "Missions/bounties/trade", "priority": "Medium", "target": "Gain inf >75%"})
        top_rep = max(self.faction_reps.values(), default=0)
        if top_rep < 45:
            actions.append({"action": "Grind rep", "priority": "Low", "target": "Top faction"})
        self.actions_changed.emit(json.dumps(actions))

class GeneralTab(TabContent):
    def __init__(self, state: GameState):
        super().__init__("Current Situation")
        self.add_row("system", "System", "Unknown", "#00eaff")
        self.add_row("sys_info", "Info", "", "#00eaff")
        self.add_row("ctrl_faction", "Controlling", "", "#00ff88")
        self.add_row("factions", "Factions", "", "#ffdd00")
        self.add_row("reputation", "Reputation", "Neutral", "#ffdd00")
        state.system_changed.connect(lambda v: self.update_row("system", v))
        state.system_info_changed.connect(lambda v: self.update_row("sys_info", v))
        state.controlling_faction_changed.connect(lambda v: self.update_row("ctrl_faction", v))
        state.faction_status_changed.connect(lambda v: self.update_row("factions", v))
        state.faction_reputation_changed.connect(lambda v: self.update_row("reputation", v))

class ExplorationTab(TabContent):
    def __init__(self, state: GameState):
        super().__init__("Exploration Status")
        self.add_row("scanned", "Scanned", "0 / 0", "#00ff88")
        self.add_row("high_value", "High Value", "None", "#ffdd00")
        self.add_row("first_discovery", "First Discovery", "Unknown", "#ff6600")
        self.add_row("exobiology", "Exobiology", "None", "#00d4ff")
        state.scanned_changed.connect(lambda v: self.update_row("scanned", v))
        state.high_value_changed.connect(lambda v: self.update_row("high_value", v))
        state.first_discovery_changed.connect(lambda v: self.update_row("first_discovery", v))
        state.exobiology_changed.connect(lambda v: self.update_row("exobiology", v))

class PowerplayTab(TabContent):
    def __init__(self, state: GameState):
        super().__init__("Powerplay")
        self.add_row("pledged", "Pledged", "None", "#00d4ff")
        self.add_row("merits", "Merits", "0", "#ff9900")
        self.add_row("sys_pp", "System PP", "None", "#ff9900")
        state.power_changed.connect(lambda v: self.update_row("pledged", v))
        state.merits_changed.connect(lambda v: self.update_row("merits", v))
        state.system_pp_state_changed.connect(lambda v: self.update_row("sys_pp", v))

class CombatTab(TabContent):
    def __init__(self, state: GameState):
        super().__init__("Combat Status")
        self.add_row("combat", "Combat", "Idle", "#ff4444")
        state.combat_changed.connect(lambda v: self.update_row("combat", v))

class ActionsTab(TabContent):
    def __init__(self, state: GameState):
        super().__init__("Recommended Actions")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Priority", "Action", "Target"])
        self.table.setStyleSheet("color: #f0f4ff; background: #0a0e17;")
        self.layout.addWidget(self.table)
        state.actions_changed.connect(self._update_table)

    def _update_table(self, json_actions):
        actions = json.loads(json_actions)
        self.table.setRowCount(len(actions))
        for i, act in enumerate(actions):
            self.table.setItem(i, 0, QTableWidgetItem(act["priority"]))
            self.table.setItem(i, 1, QTableWidgetItem(act["action"]))
            self.table.setItem(i, 2, QTableWidgetItem(act["target"]))
        self.table.resizeColumnsToContents()

class EDHelperWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EDHelper")
        self.resize(1100, 680)
        self.state = GameState()
        self._setup_theme()
        self._setup_tabs()
        self.journal_timer = QTimer(self)
        self.journal_timer.timeout.connect(self.state.check_journal)
        self.journal_timer.start(800)

    def _setup_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#0a0e17"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#e0e8ff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#000814"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#f0f4ff"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#1a2233"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#00d4ff"))
        self.setPalette(palette)

    def _setup_tabs(self):
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #1a2233; background: #0a0e17; }
            QTabBar::tab { background: #1a2233; color: #a0b0d0; padding: 10px 18px; }
            QTabBar::tab:selected { background: #00d4ff; color: #000814; }
        """)
        tabs.addTab(GeneralTab(self.state), "General")
        tabs.addTab(ExplorationTab(self.state), "Exploration")
        tabs.addTab(PowerplayTab(self.state), "Powerplay")
        tabs.addTab(CombatTab(self.state), "Combat")
        tabs.addTab(ActionsTab(self.state), "Actions")
        self.setCentralWidget(tabs)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = EDHelperWindow()
    window.show()
    sys.exit(app.exec())