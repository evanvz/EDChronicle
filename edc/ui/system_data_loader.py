import logging

logger = logging.getLogger(__name__)


class SystemDataLoader:
    """
    Owns the DB-to-state loading path for system data.
    Reads from repository, populates state, then triggers
    UI refresh callbacks.
    Knows nothing about widgets — only state and repo.
    """

    def __init__(self, state, repo, planet_values,
                 on_refresh_exploration,
                 on_refresh_materials_shortlist,
                 on_refresh_exobiology,
                 planet_value_class_name_fn):
        self.state = state
        self.repo = repo
        self.planet_values = planet_values
        self._refresh_exploration = on_refresh_exploration
        self._refresh_materials_shortlist = on_refresh_materials_shortlist
        self._refresh_exobiology = on_refresh_exobiology
        self._planet_value_class_name = planet_value_class_name_fn

    def load_last_system_data(self):
        logger.info("SystemDataLoader: loading last system from DB")
        row = self.repo.get_most_recent_system()
        if row is None:
            return

        system_address = row["system_address"]
        if not isinstance(system_address, int):
            return

        self.state.system_address = system_address
        self.state.system = row["system_name"]
        self.state.system_body_count = row["body_count"]
        self.state.fss_complete = bool(row["fss_complete"])

        self.load_current_system_data()

    def load_current_system_data(self):
        system_address = getattr(self.state, "system_address", None)
        if not isinstance(system_address, int):
            return

        row = self.repo.get_system(system_address)
        if row is not None:
            self.state.system_address = row["system_address"]
            self.state.system = row["system_name"]
            self.state.system_body_count = row["body_count"]
            self.state.fss_complete = bool(row["fss_complete"])

        existing_resolved_ids = set(
            getattr(self.state, "resolved_body_ids", set()) or set()
        )

        loaded_body_count = 0
        self.state.bodies.clear()
        self.state.body_id_to_name.clear()
        self.state.resolved_body_ids.clear()
        self.state.bio_signals.clear()
        self.state.geo_signals.clear()
        self.state.human_signals.clear()
        self.state.exo.clear()

        for row in self.repo.get_bodies(system_address):
            body_id = row["body_id"]
            body_name = row["body_name"]

            if not body_name:
                continue

            estimated_value = row["estimated_value"]
            if not isinstance(estimated_value, int) and self.planet_values:
                try:
                    estimated_value = self.planet_values.estimate(
                        planet_class=self._planet_value_class_name(
                            row["planet_class"] or ""
                        ),
                        terraformable=bool(row["terraformable"]),
                        mapped=bool(row["dss_mapped"] or row["was_mapped"]),
                        first_discovered=False,
                    )
                except Exception:
                    estimated_value = None
            import json as _json
            _mat_raw = row["materials"] if "materials" in row.keys() else None
            try:
                _materials = _json.loads(_mat_raw) if _mat_raw else {}
            except Exception:
                _materials = {}

            rec = {
                "BodyID": body_id if isinstance(body_id, int) else None,
                "BodyName": body_name,
                "PlanetClass": row["planet_class"] or "",
                "Terraformable": bool(row["terraformable"]),
                "DistanceLS": row["distance_ls"],
                "Landable": None if row["landable"] is None else bool(row["landable"]),
                "WasMapped":      bool(row["was_mapped"]),
                "DSSMapped":      bool(row["dss_mapped"]),
                "EstimatedValue": estimated_value,
                "Volcanism":      row["volcanism"] if "volcanism" in row.keys() else "",
                "Materials":      _materials,
                "FirstFootfall":  bool(row["first_footfall"]) if "first_footfall" in row.keys() else False,
                "HasFootfall":    bool(row["has_footfall"])    if "has_footfall"    in row.keys() else False,
            }

            self.state.bodies[body_name] = rec

            if isinstance(body_id, int):
                self.state.body_id_to_name[body_id] = body_name
                self.state.resolved_body_ids.add(body_id)
                loaded_body_count += 1

        if loaded_body_count == 0 and existing_resolved_ids:
            self.state.resolved_body_ids.update(existing_resolved_ids)

        for row in self.repo.get_body_signals(system_address):
            body_name = row["body_name"]
            if not body_name:
                continue

            bio = int(row["bio_signals"] or 0)
            geo = int(row["geo_signals"] or 0)
            human = int(row["human_signals"] or 0)

            self.state.bio_signals[body_name] = bio
            self.state.geo_signals[body_name] = geo
            self.state.human_signals[body_name] = human

            rec = self.state.bodies.get(body_name)
            if isinstance(rec, dict):
                rec["BioSignals"] = bio
                rec["GeoSignals"] = geo
                rec["HumanSignals"] = human

        for row in self.repo.get_dss_genus_discovery(system_address):
            body_name = row["body_name"]
            genus = row["genus"]
            if not body_name or not genus:
                continue

            cur = self.state.bio_genuses.get(body_name)
            if not isinstance(cur, list):
                cur = []
            if genus not in cur:
                cur.append(genus)
            self.state.bio_genuses[body_name] = cur

            rec = self.state.bodies.get(body_name)
            if isinstance(rec, dict):
                rec["BioGenuses"] = cur
                rec["DSSMapped"] = True

        for row in self.repo.get_exobiology(system_address):
            body_name = row["body_name"]
            genus = row["genus"]
            species = row["species"]
            variant = row["variant"]
            samples = int(row["samples"] or 0)

            if not body_name or not genus or not species or not variant:
                continue

            body = self.state.bodies.get(body_name)
            if not isinstance(body, dict):
                continue

            body_id = body.get("BodyID")
            if not isinstance(body_id, int):
                continue

            key = f"{body_id}|{genus}|{species}|{variant}"
            self.state.exo[key] = {
                "BodyID": body_id,
                "BodyName": body_name,
                "Genus": genus,
                "Species": species,
                "Variant": variant,
                "Samples": samples,
                "Complete": samples >= 3,
                "LastScanType": "DB",
            }

        self._refresh_exploration()
        self._refresh_materials_shortlist()
        self._refresh_exobiology()