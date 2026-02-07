import logging
import math
from typing import Any, Dict, List, Tuple
from .state import GameState
from .planet_values import PlanetValueTable
from .exo_values import ExoValueTable
from .external_intel import ExternalIntel
from edc.engine.handlers import exploration, exobio, inventory, powerplay, misc

log = logging.getLogger("edc.event_engine")

class EventEngine:
    def __init__(
        self,
        state: GameState,
        planet_values: PlanetValueTable | None = None,
        exo_values: ExoValueTable | None = None,
        external_intel: ExternalIntel | None = None,
    ):
        self.state = state
        self.planet_values = planet_values
        self.exo_values = exo_values
        self.external_intel = external_intel

    def _apply_external_intel(self, system_name: str | None, system_address: Any = None) -> None:
        # Advisory only; never overrides journal truth.
        try:
            if not system_name or not self.external_intel:
                self.state.external_pois = []
                return
            addr = system_address if isinstance(system_address, int) else None
            self.state.external_pois = self.external_intel.get_pois(system_name, addr)
        except Exception:
            self.state.external_pois = []

    def _classify_system_signal(self, signal_name: str, uss_type: str, is_station: Any, signal_type: Any = None) -> str:
        """
        Journal-derived classification to keep UI low-noise.
        Categories: Megaship | Station | USS | Phenomena | Other
        """
        try:
            st = (signal_type or "")
            if isinstance(st, str) and st.strip().lower() == "megaship":
                return "Megaship"
            if isinstance(is_station, bool) and is_station:
                return "Station"
            if isinstance(uss_type, str) and uss_type.strip():
                return "USS"
            s = signal_name if isinstance(signal_name, str) else ""
            sl = s.lower()
            # Heuristics for notable stellar phenomena / lagrange clouds etc.
            if any(k in sl for k in ("lagrange", "cloud", "anomal", "phenomen", "notable", "stellar")):
                return "Phenomena"
        except Exception:
            pass
        return "Other"

    def _norm_text(self, v: Any) -> str:
        """
        Normalize journal-provided strings for stable dict keys and dedupe.
        Collapses internal whitespace and strips leading/trailing spaces.
        """
        if not isinstance(v, str):
            return ""
        try:
            return " ".join(v.split())
        except Exception:
            return v.strip()

    def _parse_materials_category(self, items: Any) -> tuple[Dict[str, int], Dict[str, str]]:
        """
        Parse Materials event category list into:
          counts: name(lower) -> Count(int)
          loc:    name(lower) -> Name_Localised (or best-effort display)
        """
        counts: Dict[str, int] = {}
        loc: Dict[str, str] = {}
        if not isinstance(items, list):
            return counts, loc
        for rec in items:
            if not isinstance(rec, dict):
                continue
            nm = rec.get("Name")
            cnt = rec.get("Count")
            if not isinstance(nm, str) or not isinstance(cnt, int):
                continue
            key = nm.strip().lower()
            if not key:
                continue
            counts[key] = cnt
            nl = rec.get("Name_Localised")
            if isinstance(nl, str) and nl.strip():
                loc[key] = nl.strip()
            else:
                # Best-effort display (raw usually has no Name_Localised)
                loc[key] = key.replace("_", " ").title()
        return counts, loc

    def _parse_shiplocker_items(self, items: Any) -> tuple[Dict[str, int], Dict[str, str]]:
        """
        Parse ShipLocker.Items into aggregated inventory:
          counts: name(lower) -> total Count(int)
          loc:    name(lower) -> Name_Localised (best-effort display)
        Notes:
          - Items can repeat with different MissionID; we aggregate totals by Name.
        """
        counts: Dict[str, int] = {}
        loc: Dict[str, str] = {}
        if not isinstance(items, list):
            return counts, loc
        for rec in items:
            if not isinstance(rec, dict):
                continue
            nm = rec.get("Name")
            cnt = rec.get("Count")
            if not isinstance(nm, str) or not isinstance(cnt, int):
                continue
            key = nm.strip().lower()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + cnt
            nl = rec.get("Name_Localised")
            if isinstance(nl, str) and nl.strip():
                loc[key] = nl.strip()
            else:
                loc[key] = key.replace("_", " ").title()
        return counts, loc

    def process(self, event: Dict[str, Any]) -> Tuple[GameState, List[str]]:
        """
        Returns: (updated_state, ui_messages)
        """
        msgs: List[str] = []
        name = event.get("event")
        self.state.last_event = name

        credits_now = event.get("Credits")
        if isinstance(credits_now, int):
            self.state.credits = credits_now

        if name == "Location":
            # Happens on login; great for HUD
            new_sys = event.get("StarSystem", self.state.system)
            if new_sys and new_sys != self.state.system:
                self.state.bodies.clear()
                self.state.exo.clear()
                self.state.body_id_to_name.clear()
                self.state.bio_signals.clear()
                self.state.bio_genuses.clear()
                self.state.geo_signals.clear()
                self.state.non_body_count = None
                self.state.system_signals = []
                self.state.external_pois = []
                self.state.system_body_count = None
                self.state.system_allegiance = None
                self.state.system_government = None
                self.state.system_economy = None
                self.state.system_security = None
                self.state.population = None
                self.state.controlling_faction = None
                self.state.factions = []
                self.state.system_controlling_power = None
                self.state.system_powerplay_state = None
                self.state.system_powers = []
                self.state.system_powerplay_conflict_progress = {}
                try:
                    self.state.pp_enemy_alerts.clear()
                except Exception:
                    self.state.pp_enemy_alerts = []
                self.state.combat_contacts.clear()
                self.state.combat_current_key = ""
            self.state.system = new_sys
            self.state.in_hyperspace = False
            self.state.jump_star_class = None
            self.state.system_allegiance = event.get("SystemAllegiance")
            self.state.system_government = event.get("SystemGovernment_Localised") or event.get("SystemGovernment")
            self.state.system_economy = event.get("SystemEconomy_Localised") or event.get("SystemEconomy")
            self.state.system_security = event.get("SystemSecurity_Localised") or event.get("SystemSecurity")
            self.state.population = event.get("Population")
            cf = event.get("SystemFaction", {}) or {}
            self.state.controlling_faction = cf.get("Name")
            self.state.factions = event.get("Factions", []) or []

            # Powerplay (if present in this system)
            self.state.system_controlling_power = event.get("ControllingPower")
            self.state.system_powerplay_state = event.get("PowerplayState")
            pw = event.get("Powers") or []
            self.state.system_powers = [p for p in pw if isinstance(p, str)]
            prog = {}
            for rec in (event.get("PowerplayConflictProgress") or []):
                if isinstance(rec, dict) and isinstance(rec.get("Power"), str):
                    cp = rec.get("ConflictProgress")
                    if isinstance(cp, (int, float)):
                        prog[rec["Power"]] = float(cp)
            self.state.system_powerplay_conflict_progress = prog
            self._apply_external_intel(self.state.system, event.get("SystemAddress"))
            if self.state.system:
                msgs.append(f"Location: {self.state.system}")

        elif name == "StartJump":
            # Clear UI as soon as hyperspace starts and show destination
            if event.get("JumpType") == "Hyperspace":
                target = event.get("StarSystem")
                star_class = event.get("StarClass")

                # Clear per-system state immediately
                self.state.bodies.clear()
                self.state.exo.clear()
                self.state.body_id_to_name.clear()
                self.state.bio_signals.clear()
                self.state.bio_genuses.clear()
                self.state.geo_signals.clear()
                self.state.non_body_count = None
                self.state.system_signals = []
                self.state.external_pois = []
                self.state.system_body_count = None
                self.state.system_allegiance = None
                self.state.system_government = None
                self.state.system_economy = None
                self.state.system_security = None
                self.state.population = None
                self.state.controlling_faction = None
                self.state.factions = []
                self.state.system_controlling_power = None
                self.state.system_powerplay_state = None
                self.state.system_powers = []
                self.state.system_powerplay_conflict_progress = {}
                try:
                    self.state.pp_enemy_alerts.clear()
                except Exception:
                    self.state.pp_enemy_alerts = []
                self.state.combat_contacts.clear()
                self.state.combat_current_key = ""

                # Show "next target" right away
                self.state.system = target or self.state.system
                self.state.in_hyperspace = True
                self.state.jump_star_class = star_class
                self._apply_external_intel(self.state.system, None)

                if target:
                    msgs.append(f"Jumping to: {target} ({star_class})")

        elif name == "ShipTargeted":
            # Clear current contact info when target is dropped
            if event.get("TargetLocked") is False:
                self.state.current_contact_alert = ""
                try:
                    self.state.pp_enemy_alerts.clear()
                except Exception:
                    self.state.pp_enemy_alerts = []
                self.state.combat_current_key = ""
                return self.state, msgs

            scan_stage = event.get("ScanStage")
            if isinstance(scan_stage, int) and scan_stage < 3:
                return self.state, msgs

            # Update Combat contacts list (always, regardless of PP pledge)
            target_power = event.get("Power")
            if not isinstance(target_power, str):
                target_power = ""
            legal = event.get("LegalStatus") or ""
            is_wanted = bool(isinstance(legal, str) and legal.strip().lower() == "wanted")
            bounty = event.get("Bounty")

            rank_val = event.get("PilotRank")
            rank_name = ""
            if isinstance(rank_val, int):
                rank_map = {
                    0: "Harmless",
                    1: "Mostly Harmless",
                    2: "Novice",
                    3: "Competent",
                    4: "Expert",
                    5: "Master",
                    6: "Dangerous",
                    7: "Deadly",
                    8: "Elite",
                }
                rank_name = rank_map.get(rank_val, "")
            elif isinstance(rank_val, str):
                rank_name = rank_val.strip()

            pilot = event.get("PilotName_Localised") or event.get("PilotName") or ""
            ship = event.get("Ship_Localised") or event.get("Ship") or ""
            faction = event.get("Faction") or ""
            ts = event.get("timestamp") or ""

            # Build a stable-ish dedupe key.
            # IMPORTANT: do NOT include Power in the key (it may appear later and cause duplicate rows).
            pilot_key = (event.get("PilotName") or pilot or "UNKNOWN").strip()
            ship_key = (event.get("Ship") or ship or "UNKNOWN").strip()
            faction_key = (faction or "UNKNOWN").strip()
            key = f"{pilot_key}|{ship_key}|{faction_key}"
            try:
                self.state.combat_contacts[key] = {
                    "Pilot": pilot,
                    "Rank": rank_name,
                    "Ship": ship,
                    "Faction": faction,
                    "Power": target_power,
                    "Wanted": bool(is_wanted),
                    "Bounty": bounty if isinstance(bounty, int) else None,
                    "LastSeen": ts,
                }
                self.state.combat_current_key = key
            except Exception:
                pass

            # PP enemy ship scan alert (only after scan completes; only if pledged)
            pledged = getattr(self.state, "pp_power", None)
            if not pledged:
                return self.state, msgs

            # Context: "my PP space" == system controlled by my pledged power
            ctrl = getattr(self.state, "system_controlling_power", None)
            in_my_pp_space = bool(isinstance(ctrl, str) and ctrl == pledged)

            bounty_ok = bool(isinstance(bounty, int) and bounty >= 500_000)

            rank_ok = bool(rank_name.lower() in {"dangerous", "deadly", "elite"})
            bounty_target = bool(is_wanted and bounty_ok and rank_ok)

            pp_enemy = bool(target_power and target_power != pledged)

            # Rules:
            # 1) In my PP space: alert PP enemies even if Clean/no bounty.
            # 2) Anywhere: alert only very high-value bounty targets.
            if in_my_pp_space:
                if not (pp_enemy or bounty_target):
                    return self.state, msgs
            else:
                if not bounty_target:
                    return self.state, msgs

            who_bits = [x for x in [pilot, ship, faction] if isinstance(x, str) and x.strip()]
            who = " — ".join(who_bits) if who_bits else "Unknown target"

            parts = []
            parts.append(f"⚔️ {'PP enemy' if pp_enemy else 'High bounty'} scan: {who}")
            if rank_name:
                parts.append(f"Rank: {rank_name}")
            if target_power:
                parts.append(f"Power: {target_power}")
            if is_wanted:
                parts.append("Wanted")
            if isinstance(bounty, int) and bounty > 0:
                parts.append(f"Bounty: {bounty:,} cr")

            alert = " | ".join(parts)

            try:
                if self.state.current_contact_alert != alert:
                    self.state.current_contact_alert = alert
                    self.state.pp_enemy_alerts = [alert]
            except Exception:
                self.state.current_contact_alert = alert
                self.state.pp_enemy_alerts = [alert]

            msgs.append(alert)

        elif name == "Powerplay":
            self.state.pp_power = event.get("Power")
            self.state.pp_rank = event.get("Rank")
            self.state.pp_merits = event.get("Merits")
            if self.state.pp_power:
                msgs.append(f"PP: {self.state.pp_power} (Rank {self.state.pp_rank}, Merits {self.state.pp_merits})")

        elif name == "Cargo":
            self.state.cargo_count = event.get("Count")
            limpets = 0
            for item in event.get("Inventory", []) or []:
                if item.get("Name") == "drones":
                    limpets = int(item.get("Count", 0) or 0)
                    break
            self.state.limpets = limpets
            msgs.append(f"Cargo: {self.state.cargo_count} (Limpets {self.state.limpets})")

        elif name == "Scan":
            body = self._norm_text(event.get("BodyName"))
            if body:
                planet_class = event.get("PlanetClass") or ""
                if not planet_class:
                    return self.state, msgs
                body_id = event.get("BodyID")
                if isinstance(body_id, int):
                    self.state.body_id_to_name[body_id] = body
                terraform_state = event.get("TerraformState") or ""
                terraformable = bool(terraform_state) and terraform_state.lower() != "not terraformable"
                distance_ls = event.get("DistanceFromArrivalLS")
                landable_raw = event.get("Landable")
                landable = landable_raw if isinstance(landable_raw, bool) else None
                volcanism = event.get("Volcanism_Localised") or event.get("Volcanism") or ""
                if not isinstance(volcanism, str):
                    volcanism = ""
                materials = event.get("Materials")
                if not isinstance(materials, dict):
                    materials = {}
                # Journal provides these flags in Scan
                was_discovered = bool(event.get("WasDiscovered", False))
                was_mapped = bool(event.get("WasMapped", False))
                first_discovered = not was_discovered

                est = None
                if self.planet_values and planet_class:
                    est = self.planet_values.estimate(
                        planet_class=planet_class,
                        terraformable=terraformable,
                        mapped=was_mapped,
                        first_discovered=first_discovered,
                    )

                rec = self.state.bodies.get(body, {})
                rec.update(
                    {
                        "BodyName": body,
                        "BodyID": body_id if isinstance(body_id, int) else None,
                        "PlanetClass": planet_class,
                        "Terraformable": terraformable,
                        "DistanceLS": distance_ls,
                        "Landable": landable,
                        "Volcanism": volcanism,
                        "Materials": materials,
                        "FirstDiscovered": first_discovered,
                        "Mapped": was_mapped,
                        "EstimatedValue": est,
                    }
                )
                if body in self.state.bio_signals:
                    rec["BioSignals"] = self.state.bio_signals.get(body, 0)
                if body in self.state.bio_genuses:
                    rec["BioGenuses"] = self.state.bio_genuses.get(body, [])
                if body in self.state.geo_signals:
                    rec["GeoSignals"] = self.state.geo_signals.get(body, 0)
                self.state.bodies[body] = rec

        elif name == "SAAScanComplete":
            body = self._norm_text(event.get("BodyName"))
            if body and body in self.state.bodies:
                rec = self.state.bodies[body]
                rec["Mapped"] = True
                planet_class = rec.get("PlanetClass", "")
                terraformable = bool(rec.get("Terraformable", False))
                first_discovered = bool(rec.get("FirstDiscovered", False))
                if self.planet_values and planet_class:
                    rec["EstimatedValue"] = self.planet_values.estimate(
                        planet_class=planet_class,
                        terraformable=terraformable,
                        mapped=True,
                        first_discovered=first_discovered,
                    )
                self.state.bodies[body] = rec

        elif name == "FSSDiscoveryScan":
            # "Honk" result: tells us how many bodies exist, not what they are
            bc = event.get("BodyCount")
            if isinstance(bc, int):
                self.state.system_body_count = bc
            nb = event.get("NonBodyCount")
            if isinstance(nb, int):
                self.state.non_body_count = nb

        elif name == "FSSSignalDiscovered":
            # Discovered via FSS zoom; includes USS/Stations/Phenomena etc.
            sig_name = event.get("SignalName_Localised") or event.get("SignalName") or ""
            sig_type = event.get("SignalType") or event.get("SignalType_Localised") or ""
            uss = event.get("USSType_Localised") or event.get("USSType") or ""
            threat = event.get("ThreatLevel")
            is_station = event.get("IsStation")
            time_rem = event.get("TimeRemaining")
            ts = event.get("timestamp") or ""

            key = f"{sig_name}|{sig_type}|{uss}|{threat}|{is_station}"
            category = self._classify_system_signal(sig_name, uss, is_station, sig_type)

            entry = {
                "Key": key,
                "SignalName": sig_name,
                "SignalType": sig_type,
                "USSType": uss,
                "Category": category,
                "ThreatLevel": threat if isinstance(threat, int) else None,
                "IsStation": bool(is_station) if isinstance(is_station, bool) else None,
                "TimeRemaining": time_rem if isinstance(time_rem, (int, float)) else None,
                "LastSeen": ts if isinstance(ts, str) else "",
            }

            sigs = getattr(self.state, "system_signals", None)
            if not isinstance(sigs, list):
                sigs = []
            idx = None
            for i, s in enumerate(sigs):
                if isinstance(s, dict) and s.get("Key") == key:
                    idx = i
                    break
            if idx is None:
                sigs.append(entry)
            else:
                try:
                    sigs[idx].update(entry)
                except Exception:
                    sigs[idx] = entry

            # Keep bounded per-system (prevents long-session growth/noise)
            max_sigs = 200
            if len(sigs) > max_sigs:
                sigs = sigs[-max_sigs:]
            self.state.system_signals = sigs

        elif name == "FSSBodySignals":
            # Early hint: body has Biological and Geological signals (counts)
            body = self._norm_text(event.get("BodyName"))
            if not body:
                return self.state, msgs

            body_id = event.get("BodyID")
            if isinstance(body_id, int):
                self.state.body_id_to_name[body_id] = body

            bio = 0
            geo = 0
            for sig in (event.get("Signals") or []):
                t = (sig.get("Type") or "")
                tl = (sig.get("Type_Localised") or "")
                # Real journals often use "$SAA_SignalType_Biological;" for Type
                if ("biological" in t.lower()) or (tl.strip().lower() == "biological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        bio = c
                if ("geological" in t.lower()) or (tl.strip().lower() == "geological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        geo = c

            self.state.bio_signals[body] = bio
            self.state.geo_signals[body] = geo

            # Create or update a placeholder record so the UI can show Bio immediately
            rec = self.state.bodies.get(body)
            if not isinstance(rec, dict):
                rec = {
                    "BodyName": body,
                    "BodyID": body_id if isinstance(body_id, int) else None,
                    "PlanetClass": "",
                    "DistanceLS": None,
                    "EstimatedValue": None,
                    "Terraformable": False,
                    "FirstDiscovered": False,
                    "Mapped": False,
                }
            if isinstance(body_id, int):
                rec["BodyID"] = body_id
            rec["BioSignals"] = bio
            rec["GeoSignals"] = geo
            # IMPORTANT: preserve DSS-confirmed genera if we already have them.
            # FSSBodySignals can arrive after SAASignalsFound and would otherwise overwrite the body record.
            rec["BioGenuses"] = self.state.bio_genuses.get(body, rec.get("BioGenuses", []))
            self.state.bodies[body] = rec

        elif name == "Status":
            # Live telemetry from Status.json (lat/lon/radius) - used for CCR distance tracking.
            self.state.surface_timestamp = event.get("timestamp")
            self.state.surface_body_name = self._norm_text(event.get("BodyName")) or event.get("BodyName")

            try:
                self.state.surface_lat = float(event.get("Latitude")) if event.get("Latitude") is not None else None
            except Exception:
                self.state.surface_lat = None
            try:
                self.state.surface_lon = float(event.get("Longitude")) if event.get("Longitude") is not None else None
            except Exception:
                self.state.surface_lon = None
            try:
                self.state.surface_radius_m = float(event.get("PlanetRadius")) if event.get("PlanetRadius") is not None else None
            except Exception:
                self.state.surface_radius_m = None

            # Update CCR remaining for any active exo targets on this body (best-effort).
            try:
                lat = self.state.surface_lat
                lon = self.state.surface_lon
                R = self.state.surface_radius_m
                body_nm = self._norm_text(self.state.surface_body_name or "")
                if (
                    isinstance(lat, float)
                    and isinstance(lon, float)
                    and isinstance(R, float)
                    and R > 0
                    and body_nm
                    and isinstance(self.state.exo, dict)
                ):
                    for _k, rec in self.state.exo.items():
                        if not isinstance(rec, dict):
                            continue
                        if rec.get("Complete"):
                            continue
                        req = rec.get("CCRRequiredM")
                        pts = rec.get("SamplePoints") or []
                        if not isinstance(req, int) or req <= 0:
                            continue
                        if not isinstance(pts, list) or not pts:
                            continue

                        # Only update if body seems to match current status body.
                        rec_body_id = rec.get("BodyID")
                        rec_body_name = ""
                        if isinstance(rec_body_id, int):
                            rec_body_name = self._norm_text(self.state.body_id_to_name.get(rec_body_id, "") or "")
                        if rec_body_name and rec_body_name != body_nm:
                            continue

                        # Compute min distance from current position to any saved sample point.
                        dmin = None
                        for p in pts:
                            if not (isinstance(p, dict) and "lat" in p and "lon" in p):
                                continue
                            try:
                                plat = float(p["lat"])
                                plon = float(p["lon"])
                            except Exception:
                                continue
                            d = self._surface_distance_m(lat, lon, plat, plon, R)
                            if dmin is None or d < dmin:
                                dmin = d
                        if dmin is None:
                            continue
                        rec["CCRDistanceM"] = int(round(dmin))
                        rec["CCRRemainingM"] = int(max(0, req - rec["CCRDistanceM"]))
            except Exception:
                pass

        elif name == "SAASignalsFound":
            # DSS-confirmed: includes Biological count and (most importantly) confirmed Genuses list
            body = self._norm_text(event.get("BodyName"))
            if not body:
                return self.state, msgs

            body_id = event.get("BodyID")
            if isinstance(body_id, int):
                self.state.body_id_to_name[body_id] = body

            bio = 0
            geo = 0
            for sig in (event.get("Signals") or []):
                t = (sig.get("Type") or "")
                tl = (sig.get("Type_Localised") or "")
                if ("biological" in t.lower()) or (tl.strip().lower() == "biological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        bio = c
                if ("geological" in t.lower()) or (tl.strip().lower() == "geological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        geo = c
            if bio:
                self.state.bio_signals[body] = bio

            genuses: List[str] = []
            for g in (event.get("Genuses") or []):
                if not isinstance(g, dict):
                    continue
                gn = g.get("Genus_Localised") or g.get("Genus")
                gn = self._norm_text(gn)
                if gn:
                    genuses.append(gn)

            if genuses:
                # De-dup while keeping order
                seen = set()
                cleaned = []
                for x in genuses:
                    if x not in seen:
                        cleaned.append(x)
                        seen.add(x)
                self.state.bio_genuses[body] = cleaned

            # Create or update record so UI can show DSS-confirmed genera immediately
            rec = self.state.bodies.get(body)
            if not isinstance(rec, dict):
                rec = {
                    "BodyName": body,
                    "BodyID": body_id if isinstance(body_id, int) else None,
                    "PlanetClass": "",
                    "DistanceLS": None,
                    "EstimatedValue": None,
                    "Terraformable": False,
                    "FirstDiscovered": False,
                    "Mapped": False,
                }
            if isinstance(body_id, int):
                rec["BodyID"] = body_id

            rec["BioSignals"] = self.state.bio_signals.get(body, rec.get("BioSignals", 0))
            rec["BioGenuses"] = self.state.bio_genuses.get(body, rec.get("BioGenuses", []))
            rec["GeoSignals"] = self.state.geo_signals.get(body, rec.get("GeoSignals", 0))
            self.state.bodies[body] = rec

        elif name == "ScanOrganic":
            # Journal Manual: ScanType Log/Sample/Analyse + Genus + Species + Body (ID)
            scan_type = (event.get("ScanType") or "").strip()
            st = scan_type.lower()
            genus = self._norm_text(event.get("Genus_Localised") or event.get("Genus")) or "Unknown Genus"
            species = self._norm_text(event.get("Species_Localised") or event.get("Species")) or "Unknown Species"
            variant = self._norm_text(event.get("Variant_Localised") or event.get("Variant") or "")
            body_id = event.get("Body")
            if not isinstance(body_id, int):
                return self.state, msgs

            # If we previously created any Codex-only placeholders for this body+genus, remove them now.
            # Support both legacy keys (Body|Genus|CODEX|...) and the compact key (Body|Genus|CODEX).
            prefix = f"{body_id}|"
            for k in list(self.state.exo.keys()):
                try:
                    if not (isinstance(k, str) and k.startswith(prefix)):
                        continue
                    parts = k.split("|")
                    if len(parts) >= 3 and parts[0] == str(body_id) and parts[2] == "CODEX":
                        gk = self._norm_text(parts[1])
                        if gk == genus:
                            del self.state.exo[k]
                except Exception:
                    pass

            # Keying by (BodyID, Genus, Species) avoids duplicate rows when Variant is missing/inconsistent.
            key = f"{body_id}|{genus}|{species}"
            rec = self.state.exo.get(key, {})
            if not isinstance(rec, dict):
                rec = {}
            progress = int(rec.get("Samples", 0) or 0)

            # Migrate any legacy per-variant keys into the new per-species key.
            legacy_prefix = f"{key}|"
            for k in list(self.state.exo.keys()):
                try:
                    if not (isinstance(k, str) and k.startswith(legacy_prefix)):
                        continue
                    old = self.state.exo.get(k)
                    if isinstance(old, dict):
                        try:
                            rec["Samples"] = max(int(rec.get("Samples", 0) or 0), int(old.get("Samples", 0) or 0))
                        except Exception:
                            pass
                        rec["Complete"] = bool(rec.get("Complete") or old.get("Complete"))
                        for fld in ("Variant", "BaseValue", "PotentialValue", "LastScanType"):
                            if rec.get(fld) in (None, "", 0) and old.get(fld) not in (None, "", 0):
                                rec[fld] = old.get(fld)
                    self.state.exo.pop(k, None)
                except Exception:
                    pass

            rec.update(
                {
                    "BodyID": body_id,
                    "Genus": genus,
                    "Species": species,
                    "Variant": variant if variant else (rec.get("Variant") or ""),
                    "LastScanType": scan_type,
                }
            )
            if self.exo_values:
                val = self.exo_values.get_value(variant) or self.exo_values.get_value(species)
                if val is not None:
                    rec["BaseValue"] = val

            # CCR (minimum distance between samples) comes from exo_values.json per species. :contentReference[oaicite:1]{index=1}
            # We store sample positions from Status.json at the time of sampling.
            try:
                if "CCRRequiredM" not in rec or not isinstance(rec.get("CCRRequiredM"), int):
                    if self.exo_values and hasattr(self.exo_values, "by_species"):
                        exo_rec = self.exo_values.by_species.get(species)
                        if exo_rec is None and isinstance(species, str) and " - " in species:
                            exo_rec = self.exo_values.by_species.get(species.split(" - ", 1)[0].strip())
                        ccr = getattr(exo_rec, "ccr_m", None) if exo_rec is not None else None
                        if isinstance(ccr, int) and ccr > 0:
                            rec["CCRRequiredM"] = ccr
                if "SamplePoints" not in rec or not isinstance(rec.get("SamplePoints"), list):
                    rec["SamplePoints"] = []
            except Exception:
                pass

            # Your real process is:
            # - Log = 1/3
            # - Sample + Sample = 2/3 and 3/3
            # - Analyse confirms completion
            if st == "log":
                progress = max(progress, 1)

                # CCR init on first log
                try:
                    lat = self.state.surface_lat
                    lon = self.state.surface_lon
                    R = self.state.surface_radius_m
                    if isinstance(lat, float) and isinstance(lon, float) and isinstance(R, float) and R > 0:
                        rec["SamplePoints"] = [{
                            "t": self.state.surface_timestamp,
                            "lat": lat,
                            "lon": lon,
                        }]
                        req = rec.get("CCRRequiredM")
                        if isinstance(req, int) and req > 0:
                            rec["CCRDistanceM"] = 0
                            rec["CCRRemainingM"] = req
                except Exception:
                    pass

                # CCR INITIALISATION (first scan defines origin)
                try:
                    lat = self.state.surface_lat
                    lon = self.state.surface_lon
                    R = self.state.surface_radius_m

                    if (
                        isinstance(lat, float)
                        and isinstance(lon, float)
                        and isinstance(R, float)
                        and R > 0
                    ):
                        rec["SamplePoints"] = [{
                            "t": self.state.surface_timestamp,
                            "lat": lat,
                            "lon": lon,
                        }]

                        req = rec.get("CCRRequiredM")
                        if isinstance(req, int) and req > 0:
                            rec["CCRDistanceM"] = 0
                            rec["CCRRemainingM"] = req
                except Exception:
                    pass

            elif st == "sample":
                # Each Sample advances progress by 1 (0→1→2→3). If "Log" was missed, first sample becomes 1/3.
                progress = min(3, max(progress, 0) + 1)

                # Record sampling position (best-effort) for CCR.
                try:
                    lat = self.state.surface_lat
                    lon = self.state.surface_lon
                    R = self.state.surface_radius_m
                    if isinstance(lat, float) and isinstance(lon, float) and isinstance(R, float) and R > 0:
                        rec["SamplePoints"].append(
                            {
                                "t": self.state.surface_timestamp,
                                "lat": lat,
                                "lon": lon,
                            }
                        )
                        # Keep only last 3 sample points (game requires 3).
                        if len(rec["SamplePoints"]) > 3:
                            rec["SamplePoints"] = rec["SamplePoints"][-3:]

                    # --- CCR INITIALISATION (first sample) ---
                    # Ensure CCR is visible immediately after first sample
                    if len(rec["SamplePoints"]) == 1:
                        req = rec.get("CCRRequiredM")
                        if isinstance(req, int) and req > 0:
                            rec["CCRDistanceM"] = 0
                            rec["CCRRemainingM"] = req

                        # After adding, compute min distance from this new point to previous points.
                        req = rec.get("CCRRequiredM")
                        pts = rec.get("SamplePoints") or []
                        if isinstance(req, int) and req > 0 and isinstance(pts, list) and len(pts) >= 2:
                            # Compare newest to all earlier points
                            newest = pts[-1]
                            dmin = None
                            for p in pts[:-1]:
                                try:
                                    d = self._surface_distance_m(
                                        float(newest["lat"]),
                                        float(newest["lon"]),
                                        float(p["lat"]),
                                        float(p["lon"]),
                                        R,
                                    )
                                except Exception:
                                    continue
                                if dmin is None or d < dmin:
                                    dmin = d
                            if dmin is not None:
                                rec["CCRDistanceM"] = int(round(dmin))
                                rec["CCRRemainingM"] = int(max(0, req - rec["CCRDistanceM"]))
                except Exception:
                    pass
            elif st == "analyse":
                # Analyse confirms completion (treat as 3/3 to keep UI consistent).
                progress = max(progress, 3)

            rec["Samples"] = progress
            rec["Complete"] = (progress >= 3)

            self.state.exo[key] = rec

        elif name == "CodexEntry":
            # CodexEntry is NOT sampling progress, but it's a useful early hint.
            # We create a placeholder entry so the UI can show genus you discovered.
            body_id = event.get("BodyID")
            name_loc = event.get("Name_Localised") or ""
            entry_id = event.get("EntryID")
            v = event.get("VoucherAmount")
            if isinstance(v, int) and v > 0:
                self.state.session_codex_collected += v
            if not isinstance(body_id, int) or not isinstance(name_loc, str) or not name_loc.strip():
                return self.state, msgs

            # Genus is the first word in the localized name (e.g., "Stratum Tectonicas - Lime")
            genus = self._norm_text(name_loc.strip().split(" ", 1)[0].strip())
            if not genus:
                return self.state, msgs

            # If we already have a real ScanOrganic record for this body+genus, do NOT create a CODEX placeholder.
            # This prevents "completed" scans from re-appearing as CODEX noise.
            try:
                for _k, _r in (self.state.exo or {}).items():
                    if not isinstance(_r, dict):
                        continue
                    if _r.get("BodyID") != body_id:
                        continue
                    g = str(_r.get("Genus", "") or "").strip()
                    last = str(_r.get("LastScanType", "") or "").strip().upper()
                    if last != "CODEX" and g == genus:
                        return self.state, msgs
            except Exception:
                pass

            # Potential value: journal doesn't provide this for CodexEntry. Best-effort derive from exo_values.json.
            pot = None
            if self.exo_values:
                try:
                    nm = name_loc.strip()
                    exo_rec = self.exo_values.by_species.get(nm) if hasattr(self.exo_values, "by_species") else None
                    if exo_rec is None and " - " in nm:
                        exo_rec = self.exo_values.by_species.get(nm.split(" - ", 1)[0].strip())
                    if exo_rec:
                        genus = exo_rec.genus or genus
                        pot = exo_rec.base_value
                    else:
                        pot = self.exo_values.get_value(nm) or (
                            self.exo_values.get_value(nm.split(" - ", 1)[0].strip()) if " - " in nm else None
                        )
                except Exception:
                    pot = None

            # Best-effort: populate Species/Variant for CODEX placeholders so the UI isn't blank.
            # Typical format: "<Species> - <Variant>" (e.g., "Stratum Tectonicas - Lime")
            species_txt = name_loc.strip()
            variant_txt = ""
            try:
                nm_full = name_loc.strip()
                if " - " in nm_full:
                    left, right = nm_full.split(" - ", 1)
                    species_txt = left.strip()
                    variant_txt = right.strip()
            except Exception:
                species_txt = name_loc.strip()
                variant_txt = ""

            # If exo_values has canonical fields, prefer those (guarded).
            try:
                if self.exo_values:
                    nm = name_loc.strip()
                    exo_rec = self.exo_values.by_species.get(nm) if hasattr(self.exo_values, "by_species") else None
                    if exo_rec:
                        species_txt = getattr(exo_rec, "species", None) or species_txt
                        variant_txt = getattr(exo_rec, "variant", None) or variant_txt
            except Exception:
                pass

            # Dedupe: CodexEntry can fire multiple times for the same body+genus. Keep exactly one placeholder.
            codex_key = f"{body_id}|{genus}|CODEX"
            try:
                legacy_prefix = f"{body_id}|{genus}|CODEX|"
                for k in list((self.state.exo or {}).keys()):
                    if isinstance(k, str) and k.startswith(legacy_prefix):
                        self.state.exo.pop(k, None)
            except Exception:
                pass

            rec = self.state.exo.get(codex_key, {})

            # Add localized fields so UI matching/labels stay consistent with SAASignalsFound.
            # Example Name_Localised: "Bacterium Cerbrus - Teal"
            variant_loc = (name_loc or "").strip()
            species_loc = variant_loc.split(" - ", 1)[0].strip() if variant_loc else ""
            genus_loc = species_loc.split(" ", 1)[0].strip() if species_loc else ""

            rec.update(
                {
                    "BodyID": body_id,
                    "Genus": genus,
                    "Genus_Localised": genus_loc,
                    "Species": species_txt,
                    "Species_Localised": species_loc,
                    "Variant": variant_txt,
                    "Variant_Localised": variant_loc,
                    "Samples": 0,
                    "Complete": False,
                    "LastScanType": "CODEX",
                    "CodexEntryID": entry_id,
                    "CodexName": name_loc.strip(),
                    "BaseValue": pot,
                    "PotentialValue": pot,
                }
            )
            self.state.exo[codex_key] = rec

        elif name == "SellOrganicData":
            # Session ledger: sum Value + Bonus for all items sold
            total = 0
            for item in (event.get("BioData") or []):
                v = item.get("Value", 0)
                b = item.get("Bonus", 0)
                if isinstance(v, int):
                    total += v
                if isinstance(b, int):
                    total += b
            if total > 0:
                self.state.session_exo_earnings += total
                msgs.append(f"Exobiology sold: {total:,} cr")

        # Dispatch order matters slightly: inventory first, then exploration/exobio, then PP, then misc.
        handled = False
        for fn in (
            inventory.handle,
            exploration.handle,
            exobio.handle,
            powerplay.handle,
            misc.handle,
        ):
            try:
                if fn(self, name, event, msgs):
                    handled = True
                    break
            except Exception:
                log.exception("Handler error for event=%s in %s", name, getattr(fn, "__module__", "handler"))
                handled = True
                break

        return self.state, msgs

    def _surface_distance_m(
        self,
        lat1_deg: float,
        lon1_deg: float,
        lat2_deg: float,
        lon2_deg: float,
        radius_m: float,
    ) -> float:
        """
        Great-circle distance between two lat/lon points on a sphere (meters).
        """
        lat1 = math.radians(lat1_deg)
        lon1 = math.radians(lon1_deg)
        lat2 = math.radians(lat2_deg)
        lon2 = math.radians(lon2_deg)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * (math.sin(dlon / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return float(radius_m) * c