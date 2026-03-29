from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging

log = logging.getLogger(__name__)


def _parse_journal_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _norm_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _terraformable_from_state(terraform_state: Any) -> int | None:
    if not isinstance(terraform_state, str):
        return 0
    state = terraform_state.strip().lower()
    if not state:
        return 0
    return 0 if state == "not terraformable" else 1


def _surface_signal_counts(signals: Any) -> tuple[int, int, int]:
    bio = 0
    geo = 0
    human = 0

    if not isinstance(signals, list):
        return bio, geo, human

    for sig in signals:
        if not isinstance(sig, dict):
            continue

        sig_type = str(sig.get("Type") or "").lower()
        sig_type_loc = str(sig.get("Type_Localised") or "").strip().lower()
        count = sig.get("Count", 0)
        if not isinstance(count, int):
            count = 0

        if ("biological" in sig_type) or (sig_type_loc == "biological"):
            bio = count
        if ("geological" in sig_type) or (sig_type_loc == "geological"):
            geo = count
        if ("human" in sig_type) or (sig_type_loc == "human"):
            human = count

    return bio, geo, human


@dataclass
class CachedBody:
    body_id: int
    body_name: str
    planet_class: str | None = None
    terraformable: int | None = 0
    landable: int | None = None
    was_mapped: int | None = 0
    dss_mapped: int | None = 0
    estimated_value: int | None = None
    distance_ls: float | None = None


@dataclass
class SystemVisit:
    system_address: int
    system_name: str | None
    first_visit: str | None
    last_visit: str | None
    visit_count: int = 0
    body_count: int | None = None
    fss_complete: int = 0


class JournalImporter:
    def __init__(self, journal_dir: Path, repo):
        self.journal_dir = Path(journal_dir)
        self.repo = repo

        self.current_system_address: int | None = None
        self.current_system_name: str | None = None

        self.body_id_to_name: dict[int, str] = {}
        self.bodies_by_name: dict[str, CachedBody] = {}
        self.system_visits: dict[int, SystemVisit] = {}

    def import_all(self) -> None:
        if not self.journal_dir.exists():
            log.warning("Journal directory not found: %s", self.journal_dir)
            return

        files = sorted(self.journal_dir.glob("Journal.*.log"))
        log.info("Historical importer scanning %d journal files", len(files))

        for path in files:
            try:
                size = path.stat().st_size
            except OSError:
                log.exception("Could not stat journal file: %s", path)
                continue

            if self.repo.journal_processed(path.name, size):
                continue

            log.info("Importing historical journal: %s", path.name)
            self._process_file(path)
            processed_at = datetime.now(timezone.utc).isoformat()
            self.repo.mark_journal_processed(path.name, size, processed_at)

    def _process_file(self, path: Path) -> None:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line_number, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except Exception:
                    log.warning("Skipping invalid JSON in %s at line %d", path.name, line_number)
                    continue

                if not isinstance(event, dict):
                    continue

                try:
                    self._process_event(event)
                except Exception:
                    log.exception(
                        "Failed processing event %s in %s at line %d",
                        event.get("event"),
                        path.name,
                        line_number,
                    )

    def _process_event(self, event: dict[str, Any]) -> None:
        name = event.get("event")
        if not isinstance(name, str):
            return

        if name == "Location":
            self._handle_location(event)
        elif name == "FSDJump":
            self._handle_fsdjump(event)
        elif name == "FSSDiscoveryScan":
            self._handle_fss_discovery_scan(event)
        elif name == "FSSBodySignals":
            self._handle_signal_event(event)
        elif name == "SAASignalsFound":
            self._handle_signal_event(event)
        elif name == "Scan":
            self._handle_scan(event)
        elif name == "SAAScanComplete":
            self._handle_saa_scan_complete(event)
        elif name == "ScanOrganic":
            self._handle_scan_organic(event)

    def _upsert_visit(
        self,
        system_address: int,
        system_name: str | None,
        timestamp: str | None,
        increment_visit: bool,
    ) -> None:
        visit = self.system_visits.get(system_address)
        if visit is None:
            existing = self.repo.get_system_details(system_address)
            existing_first_visit = None
            existing_last_visit = None
            existing_visit_count = 0

            if existing is not None:
                existing_first_visit = existing["first_visit"]
                existing_last_visit = existing["last_visit"]
                existing_visit_count = existing["visit_count"] or 0

            visit = SystemVisit(
                system_address=system_address,
                system_name=system_name,
                first_visit=existing_first_visit or timestamp,
                last_visit=existing_last_visit or timestamp,
                visit_count=existing_visit_count,
            )
            self.system_visits[system_address] = visit

        if system_name:
            visit.system_name = system_name

        if timestamp:
            if not visit.first_visit or timestamp < visit.first_visit:
                visit.first_visit = timestamp
            if not visit.last_visit or timestamp > visit.last_visit:
                visit.last_visit = timestamp

        if increment_visit:
            visit.visit_count += 1

        self.repo.save_system(
            system_address=visit.system_address,
            system_name=visit.system_name,
            body_count=visit.body_count,
            fss_complete=visit.fss_complete,
            first_visit=visit.first_visit,
            last_visit=visit.last_visit,
            visit_count=visit.visit_count,
        )

    def _save_current_system(self) -> None:
        if self.current_system_address is None:
            return
        visit = self.system_visits.get(self.current_system_address)
        if visit is None:
            return

        self.repo.save_system(
            system_address=visit.system_address,
            system_name=visit.system_name,
            body_count=visit.body_count,
            fss_complete=visit.fss_complete,
            first_visit=visit.first_visit,
            last_visit=visit.last_visit,
            visit_count=visit.visit_count,
        )

    def _set_current_system(self, system_address: int, system_name: str | None) -> None:
        if self.current_system_address != system_address:
            self.body_id_to_name.clear()
            self.bodies_by_name.clear()

        self.current_system_address = system_address
        self.current_system_name = system_name

    def _handle_location(self, event: dict[str, Any]) -> None:
        system_address = event.get("SystemAddress")
        system_name = _norm_text(event.get("StarSystem"))
        timestamp = _parse_journal_timestamp(event.get("timestamp"))

        if not isinstance(system_address, int):
            return

        self._set_current_system(system_address, system_name or None)
        self._upsert_visit(
            system_address=system_address,
            system_name=system_name or None,
            timestamp=timestamp,
            increment_visit=True,
        )

        body_count = event.get("BodyCount")
        if isinstance(body_count, int):
            visit = self.system_visits[system_address]
            visit.body_count = body_count
            self._save_current_system()

    def _handle_fsdjump(self, event: dict[str, Any]) -> None:
        system_address = event.get("SystemAddress")
        system_name = _norm_text(event.get("StarSystem"))
        timestamp = _parse_journal_timestamp(event.get("timestamp"))

        if not isinstance(system_address, int):
            return

        self._set_current_system(system_address, system_name or None)
        self._upsert_visit(
            system_address=system_address,
            system_name=system_name or None,
            timestamp=timestamp,
            increment_visit=True,
        )

    def _handle_fss_discovery_scan(self, event: dict[str, Any]) -> None:
        system_address = event.get("SystemAddress")
        if not isinstance(system_address, int):
            system_address = self.current_system_address
        if not isinstance(system_address, int):
            return

        if system_address not in self.system_visits:
            self.system_visits[system_address] = SystemVisit(
                system_address=system_address,
                system_name=self.current_system_name,
                first_visit=None,
                last_visit=None,
                visit_count=0,
            )

        visit = self.system_visits[system_address]

        body_count = event.get("BodyCount")
        if isinstance(body_count, int):
            visit.body_count = body_count

        progress = event.get("Progress")
        if isinstance(progress, (int, float)):
            visit.fss_complete = 1 if progress >= 1.0 else 0

        self.repo.save_system(
            system_address=visit.system_address,
            system_name=visit.system_name,
            body_count=visit.body_count,
            fss_complete=visit.fss_complete,
            first_visit=visit.first_visit,
            last_visit=visit.last_visit,
            visit_count=visit.visit_count,
        )

    def _handle_signal_event(self, event: dict[str, Any]) -> None:
        system_address = event.get("SystemAddress")
        if not isinstance(system_address, int):
            system_address = self.current_system_address
        if not isinstance(system_address, int):
            return

        body_name = _norm_text(event.get("BodyName"))
        if not body_name:
            return

        body_id = event.get("BodyID")
        if isinstance(body_id, int):
            self.body_id_to_name[body_id] = body_name

        if event.get("event") == "SAASignalsFound":
            genuses = event.get("Genuses")
            if isinstance(genuses, list):
                for genus_entry in genuses:
                    if not isinstance(genus_entry, dict):
                        continue
                    genus = _norm_text(
                        genus_entry.get("Genus_Localised")
                        or genus_entry.get("Genus")
                    )
                    if not genus:
                        continue
                    self.repo.save_dss_genus_discovery(
                        system_address=system_address,
                        body_name=body_name,
                        genus=genus,
                    )

            cached = self.bodies_by_name.get(body_name)
            if cached is None:
                cached = CachedBody(
                    body_id=body_id if isinstance(body_id, int) else -1,
                    body_name=body_name,
                )

            cached.dss_mapped = 1
            self.bodies_by_name[body_name] = cached

            if isinstance(cached.body_id, int) and cached.body_id >= 0:
                self.repo.save_body(
                    system_address=system_address,
                    body_id=cached.body_id,
                    body_name=cached.body_name,
                    planet_class=cached.planet_class,
                    terraformable=cached.terraformable,
                    landable=cached.landable,
                    was_mapped=cached.was_mapped,
                    dss_mapped=cached.dss_mapped,
                    estimated_value=cached.estimated_value,
                    distance_ls=cached.distance_ls,
                )

        bio, geo, human = _surface_signal_counts(event.get("Signals"))
        self.repo.save_body_signals(system_address, body_name, bio, geo, human)

        cached = self.bodies_by_name.get(body_name)
        if cached is None:
            cached = CachedBody(
                body_id=body_id if isinstance(body_id, int) else -1,
                body_name=body_name,
            )
        elif isinstance(body_id, int):
            cached.body_id = body_id

        self.bodies_by_name[body_name] = cached

    def _handle_scan(self, event: dict[str, Any]) -> None:
        system_address = event.get("SystemAddress")
        if not isinstance(system_address, int):
            system_address = self.current_system_address
        if not isinstance(system_address, int):
            return

        body_name = _norm_text(event.get("BodyName"))
        if not body_name:
            return

        planet_class = event.get("PlanetClass") or ""
        if not isinstance(planet_class, str) or not planet_class:
            return

        body_id = event.get("BodyID")
        if not isinstance(body_id, int):
            return

        self.body_id_to_name[body_id] = body_name

        terraformable = _terraformable_from_state(event.get("TerraformState"))

        landable_raw = event.get("Landable")
        landable = int(bool(landable_raw)) if isinstance(landable_raw, bool) else None

        was_mapped = int(bool(event.get("WasMapped", False)))
        distance_ls = event.get("DistanceFromArrivalLS")
        if not isinstance(distance_ls, (int, float)):
            distance_ls = None

        estimated_value = event.get("EstimatedValue")
        if not isinstance(estimated_value, int):
            estimated_value = None

        self.repo.save_body(
            system_address=system_address,
            body_id=body_id,
            body_name=body_name,
            planet_class=planet_class,
            terraformable=terraformable,
            landable=landable,
            was_mapped=was_mapped,
            dss_mapped=0,
            estimated_value=estimated_value,
            distance_ls=float(distance_ls) if distance_ls is not None else None,
        )

        self.bodies_by_name[body_name] = CachedBody(
            body_id=body_id,
            body_name=body_name,
            planet_class=planet_class,
            terraformable=terraformable,
            landable=landable,
            was_mapped=was_mapped,
            dss_mapped=0,
            estimated_value=estimated_value,
            distance_ls=float(distance_ls) if distance_ls is not None else None,
        )

    def _handle_saa_scan_complete(self, event: dict[str, Any]) -> None:
        system_address = event.get("SystemAddress")
        if not isinstance(system_address, int):
            system_address = self.current_system_address
        if not isinstance(system_address, int):
            return

        body_name = _norm_text(event.get("BodyName"))
        if not body_name:
            return

        cached = self.bodies_by_name.get(body_name)
        if cached is None or not isinstance(cached.body_id, int) or cached.body_id < 0:
            return

        cached.dss_mapped = 1

        self.repo.save_body(
            system_address=system_address,
            body_id=cached.body_id,
            body_name=cached.body_name,
            planet_class=cached.planet_class,
            terraformable=cached.terraformable,
            landable=cached.landable,
            was_mapped=cached.was_mapped,
            dss_mapped=cached.dss_mapped,
            estimated_value=cached.estimated_value,
            distance_ls=cached.distance_ls,
        )

    def _handle_scan_organic(self, event: dict[str, Any]) -> None:
        system_address = event.get("SystemAddress")
        if not isinstance(system_address, int):
            system_address = self.current_system_address
        if not isinstance(system_address, int):
            return

        body_id = event.get("Body")
        if not isinstance(body_id, int):
            return

        body_name = self.body_id_to_name.get(body_id)
        if not body_name:
            return

        genus = _norm_text(event.get("Genus_Localised") or event.get("Genus"))
        species = _norm_text(event.get("Species_Localised") or event.get("Species"))
        variant = _norm_text(event.get("Variant_Localised") or event.get("Variant"))
        if not genus or not species or not variant:
            return

        scan_type = str(event.get("ScanType") or "").strip().lower()
        if scan_type != "analyse":
            return

        self.repo.save_exobiology(
            system_address=system_address,
            body_name=body_name,
            genus=genus,
            species=species,
            variant=variant,
            samples=3,
        )