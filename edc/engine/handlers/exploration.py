from __future__ import annotations
from typing import Any, Dict, List

def _pretty_token(v: Any) -> Any:
    """
    Convert Frontier internal tokens like '$economy_Extraction;' into 'Extraction'.
    If v isn't a string or doesn't look like a token, return it unchanged.
    """
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s:
        return s
    # Strip $ prefix and trailing semicolon used by journal tokens
    if s.startswith("$"):
        s = s[1:]
    if s.endswith(";"):
        s = s[:-1]

    # Remove common prefixes (case sensitive variants seen in journals)
    for prefix in ("government_", "economy_", "SYSTEM_SECURITY_", "system_security_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break

    # Best-effort formatting
    s = s.replace("_", " ").strip()
    if s:
        s = s[0].upper() + s[1:]
    return s


def handle(engine, name: str | None, event: Dict[str, Any], msgs: List[str]) -> bool:
    """
    Exploration / scanning / system & body discovery events.
    Returns True if handled.
    """

    if name == "FSDJump":
        new_sys = event.get("StarSystem")
        if new_sys and new_sys != engine.state.system:
            engine.state.bodies.clear()
            engine.state.exo.clear()
            engine.state.body_id_to_name.clear()
            engine.state.bio_signals.clear()
            engine.state.bio_genuses.clear()
            engine.state.geo_signals.clear()
            engine.state.non_body_count = None
            engine.state.system_signals = []
            engine.state.external_pois = []
            engine.state.system_body_count = None
            engine.state.system_allegiance = None
            engine.state.system_government = None
            engine.state.system_economy = None
            engine.state.system_security = None
            engine.state.population = None
            engine.state.controlling_faction = None
            engine.state.factions = []
            engine.state.system_controlling_power = None
            engine.state.system_powerplay_state = None
            engine.state.system_powers = []
            engine.state.system_powerplay_conflict_progress = {}
            try:
                engine.state.visited_systems.add(str(new_sys))
            except Exception:
                pass

        engine.state.system = new_sys or engine.state.system
        engine.state.system_address = event.get("SystemAddress") if isinstance(event.get("SystemAddress"), int) else engine.state.system_address
        engine.state.star_class = event.get("StarClass") or engine.state.star_class

        # Capture key system meta where present
        # Prefer Localised fields; otherwise sanitize token strings.
        engine.state.system_allegiance = (
            event.get("SystemAllegiance_Localised")
            or _pretty_token(event.get("SystemAllegiance"))
            or engine.state.system_allegiance
        )
        engine.state.system_government = (
            event.get("SystemGovernment_Localised")
            or _pretty_token(event.get("SystemGovernment"))
            or engine.state.system_government
        )
        engine.state.system_economy = (
            event.get("SystemEconomy_Localised")
            or _pretty_token(event.get("SystemEconomy"))
            or engine.state.system_economy
        )
        engine.state.system_security = (
            event.get("SystemSecurity_Localised")
            or _pretty_token(event.get("SystemSecurity"))
            or engine.state.system_security
        )
        engine.state.population = event.get("Population") if isinstance(event.get("Population"), int) else engine.state.population
        engine.state.controlling_faction = event.get("SystemFaction", {}).get("Name") if isinstance(event.get("SystemFaction"), dict) else engine.state.controlling_faction
        engine.state.factions = event.get("Factions") if isinstance(event.get("Factions"), list) else engine.state.factions

        # Powerplay system fields (if journal provides them)
        engine.state.system_controlling_power = event.get("ControllingPower") or engine.state.system_controlling_power
        engine.state.system_powerplay_state = event.get("PowerplayState") or engine.state.system_powerplay_state
        engine.state.system_powers = event.get("Powers") if isinstance(event.get("Powers"), list) else engine.state.system_powers
        engine.state.system_powerplay_conflict_progress = (
            event.get("PowerplayConflictProgress") if isinstance(event.get("PowerplayConflictProgress"), dict) else engine.state.system_powerplay_conflict_progress
        )

        # Advisory-only external intel
        engine._apply_external_intel(engine.state.system, engine.state.system_address)
        return True

    elif name == "Location":
        sys_name = event.get("StarSystem")
        if sys_name:
            engine.state.system = sys_name
        engine.state.system_address = event.get("SystemAddress") if isinstance(event.get("SystemAddress"), int) else engine.state.system_address
        engine.state.star_class = event.get("StarClass") or engine.state.star_class

        # Prefer Localised fields; otherwise sanitize token strings.
        engine.state.system_allegiance = (
            event.get("SystemAllegiance_Localised")
            or _pretty_token(event.get("SystemAllegiance"))
            or engine.state.system_allegiance
        )
        engine.state.system_government = (
            event.get("SystemGovernment_Localised")
            or _pretty_token(event.get("SystemGovernment"))
            or engine.state.system_government
        )
        engine.state.system_economy = (
            event.get("SystemEconomy_Localised")
            or _pretty_token(event.get("SystemEconomy"))
            or engine.state.system_economy
        )
        engine.state.system_security = (
            event.get("SystemSecurity_Localised")
            or _pretty_token(event.get("SystemSecurity"))
            or engine.state.system_security
        )

        # Update external intel on Location as well (useful on game load)
        engine._apply_external_intel(engine.state.system, engine.state.system_address)
        return True

    elif name == "StartJump":
        # Pre-jump hinting
        jump_type = event.get("JumpType")
        if jump_type:
            engine.state.last_jump_type = jump_type
        dest = event.get("StarSystem")
        if dest:
            engine.state.pending_system = dest
        return True

    elif name == "Scan":
        # Body scan (DSS/FSS)
        body_name = event.get("BodyName")
        body_id = event.get("BodyID")
        if isinstance(body_id, int) and isinstance(body_name, str) and body_name.strip():
            engine.state.body_id_to_name[body_id] = body_name

        if isinstance(body_name, str) and body_name.strip():
            engine.state.last_body = body_name

        # Store scan record in bodies dict keyed by BodyName
        if isinstance(body_name, str) and body_name.strip():
            engine.state.bodies[body_name] = event

        # Value estimate (if table is present)
        try:
            if engine.planet_values and isinstance(body_name, str) and body_name.strip():
                val = engine.planet_values.estimate_base_value(event)
                engine.state.bodies[body_name]["EstimatedValue"] = val
        except Exception:
            pass
        return True

    elif name == "SAAScanComplete":
        # Mark DSS complete
        body = event.get("BodyName")
        if isinstance(body, str) and body.strip():
            rec = engine.state.bodies.get(body) or {}
            rec["SAAScanComplete"] = True
            engine.state.bodies[body] = rec
        return True

    elif name == "FSSDiscoveryScan":
        # Total bodies and non-body signal count
        bc = event.get("BodyCount")
        nbc = event.get("NonBodyCount")
        if isinstance(bc, int):
            engine.state.system_body_count = bc
        if isinstance(nbc, int):
            engine.state.non_body_count = nbc
        return True

    elif name == "FSSSignalDiscovered":
        # System-level signal classification
        sig_type = event.get("SignalType")
        sig_name = event.get("SignalName")
        if isinstance(sig_type, str):
            # EventEngine expects: (sig_type, sig_name, is_station)
            # Best-effort inference; default to False.
            is_station = bool(event.get("IsStation")) if "IsStation" in event else False
            cls = engine._classify_system_signal(sig_type, sig_name, is_station)
            engine.state.system_signals.append(cls)
        return True

    elif name == "FSSBodySignals":
        # Per-body biological/geological signal counts
        body = event.get("BodyName")
        if not (isinstance(body, str) and body.strip()):
            return True

        bio = event.get("Signals", {}).get("Biological") if isinstance(event.get("Signals"), dict) else None
        geo = event.get("Signals", {}).get("Geological") if isinstance(event.get("Signals"), dict) else None

        if isinstance(bio, list):
            engine.state.bio_signals[body] = len(bio)
        if isinstance(geo, list):
            engine.state.geo_signals[body] = len(geo)
        return True

    elif name == "SAASignalsFound":
        # DSS signals found (biological/genus)
        body = event.get("BodyName")
        if not (isinstance(body, str) and body.strip()):
            return True

        sigs = event.get("Signals")
        if isinstance(sigs, list):
            # Save raw
            engine.state.saa_signals[body] = sigs

            # Extract genus list (best-effort)
            genuses = []
            for s in sigs:
                if not isinstance(s, dict):
                    continue
                g = s.get("Genus")
                if isinstance(g, str) and g.strip():
                    genuses.append(g.strip())
            if genuses:
                engine.state.bio_genuses[body] = sorted(set(genuses))
        return True

    elif name == "CodexEntry":
        # Keep codex status / last codex entry
        entry = event.get("Name_Localised") or event.get("Name")
        if isinstance(entry, str) and entry.strip():
            engine.state.last_codex = entry.strip()
        return True

    elif name == "MultiSellExplorationData":
        # Session ledger: exploration data sold
        total = event.get("TotalEarnings")
        if isinstance(total, int):
            engine.state.session_exploration_earnings += total
            msgs.append(f"Exploration sold: {total:,} cr")
        return True

    return False
