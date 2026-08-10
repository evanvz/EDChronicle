"""Material Trader advisor — suggests trading an excess material for one
you're short on, using the real up/down-trade mechanic.

The exact trade math isn't reliably documented anywhere consistent (two
independent wiki-summary searches gave internally-contradictory ratios).
Both the grouping data below and the trade formulas were sourced directly
from EDEngineer (https://github.com/msarilar/EDEngineer, MIT licensed), a
mature, widely-used community tool built for this exact purpose —
specifically EDEngineer.Models/MaterialTrading/MaterialTrader.cs (the
trade-finding logic) and EDEngineer/Resources/Data/entryData.json (the
material dataset), current as of that repo's master branch in Aug 2026.

Real trade rules (confirmed from EDEngineer's own working code):
- Materials never trade across Raw/Manufactured/Encoded.
- Same "Group" (family), any grade: 3:1 trading down a grade, 6:1 trading
  up a grade, multiplicative per grade crossed.
- Different group, same kind: only down-or-equal grade is possible at
  all (trading a lower grade material up into a different family can't
  be done) — flat 6:1 at equal grade, or a 2x-penalty variant of the
  down-grade formula when also dropping grade.

Odyssey suit/weapon materials are a different game system entirely
(different vendors, not this Material Trader) and are deliberately not
in this table.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple, TypedDict

# {internal_name: (grade 1-5, trade group/family, "raw"/"manufactured"/"encoded")}
_MATERIAL_INFO: Dict[str, Tuple[int, str, str]] = {
    'aberrantshieldpatternanalysis': (4, 'ShieldData', 'encoded'),
    'adaptiveencryptorscapture': (5, 'EncryptionFiles', 'encoded'),
    'ancientbiologicaldata': (3, 'GuardianRuins', 'encoded'),
    'ancientculturaldata': (2, 'GuardianRuins', 'encoded'),
    'ancienthistoricaldata': (1, 'GuardianRuins', 'encoded'),
    'ancientlanguagedata': (4, 'GuardianRuins', 'encoded'),
    'ancienttechnologicaldata': (5, 'GuardianRuins', 'encoded'),
    'anomalousbulkscandata': (1, 'DataArchives', 'encoded'),
    'anomalousfsdtelemetry': (2, 'WakeScans', 'encoded'),
    'antimony': (4, 'Category7', 'raw'),
    'archivedemissiondata': (2, 'EmissionData', 'encoded'),
    'arsenic': (2, 'Category6', 'raw'),
    'atypicaldisruptedwakeechoes': (1, 'WakeScans', 'encoded'),
    'atypicalencryptionarchives': (4, 'EncryptionFiles', 'encoded'),
    'basicconductors': (1, 'Conductive', 'manufactured'),
    'biotechconductors': (5, 'Conductive', 'manufactured'),
    'boron': (3, 'Category7', 'raw'),
    'cadmium': (3, 'Category3', 'raw'),
    'carbon': (1, 'Category1', 'raw'),
    'chemicaldistillery': (3, 'Chemical', 'manufactured'),
    'chemicalmanipulators': (4, 'Chemical', 'manufactured'),
    'chemicalprocessors': (2, 'Chemical', 'manufactured'),
    'chemicalstorageunits': (1, 'Chemical', 'manufactured'),
    'chromium': (2, 'Category2', 'raw'),
    'classifiedscandata': (5, 'DataArchives', 'encoded'),
    'compactcomposites': (1, 'Composite', 'manufactured'),
    'compactemissionsdata': (5, 'EmissionData', 'encoded'),
    'compoundshielding': (4, 'Shielding', 'manufactured'),
    'conductiveceramics': (3, 'Conductive', 'manufactured'),
    'conductivecomponents': (2, 'Conductive', 'manufactured'),
    'conductivepolymers': (4, 'Conductive', 'manufactured'),
    'configurablecomponents': (4, 'MechanicalComponents', 'manufactured'),
    'crackedindustrialfirmware': (3, 'EncodedFirmware', 'encoded'),
    'crystalshards': (1, 'Crystals', 'manufactured'),
    'dataminedwakeexceptions': (5, 'WakeScans', 'encoded'),
    'decodedemissiondata': (4, 'EmissionData', 'encoded'),
    'distortedshieldcyclerecordings': (1, 'ShieldData', 'encoded'),
    'eccentrichyperspacetrajectories': (4, 'WakeScans', 'encoded'),
    'electrochemicalarrays': (3, 'Capacitors', 'manufactured'),
    'emissiondata': (3, 'EmissionData', 'encoded'),
    'encodedscandata': (4, 'DataArchives', 'encoded'),
    'exceptionalscrambledemissiondata': (1, 'EmissionData', 'encoded'),
    'exquisitefocuscrystals': (5, 'Crystals', 'manufactured'),
    'fedcorecomposites': (5, 'Composite', 'manufactured'),
    'fedproprietarycomposites': (4, 'Composite', 'manufactured'),
    'filamentcomposites': (2, 'Composite', 'manufactured'),
    'focuscrystals': (3, 'Crystals', 'manufactured'),
    'galvanisingalloys': (2, 'Alloys', 'manufactured'),
    'germanium': (2, 'Category5', 'raw'),
    'gridresistors': (1, 'Capacitors', 'manufactured'),
    'guardian_moduleblueprint': (5, 'GuardianRuinsActive', 'encoded'),
    'guardian_powercell': (1, 'GuardianRuinsActive', 'manufactured'),
    'guardian_powerconduit': (2, 'GuardianRuinsActive', 'manufactured'),
    'guardian_sentinel_weaponparts': (3, 'GuardianRuinsActive', 'manufactured'),
    'guardian_sentinel_wreckagecomponents': (1, 'GuardianRuinsActive', 'manufactured'),
    'guardian_techcomponent': (3, 'GuardianRuinsActive', 'manufactured'),
    'guardian_vesselblueprint': (5, 'GuardianRuinsActive', 'encoded'),
    'guardian_weaponblueprint': (5, 'GuardianRuinsActive', 'encoded'),
    'heatconductionwiring': (1, 'Heat', 'manufactured'),
    'heatdispersionplate': (2, 'Heat', 'manufactured'),
    'heatexchangers': (3, 'Heat', 'manufactured'),
    'heatresistantceramics': (2, 'Thermic', 'manufactured'),
    'heatvanes': (4, 'Heat', 'manufactured'),
    'highdensitycomposites': (3, 'Composite', 'manufactured'),
    'hybridcapacitors': (2, 'Capacitors', 'manufactured'),
    'imperialshielding': (5, 'Shielding', 'manufactured'),
    'improvisedcomponents': (5, 'MechanicalComponents', 'manufactured'),
    'inconsistentshieldsoakanalysis': (2, 'ShieldData', 'encoded'),
    'iron': (1, 'Category4', 'raw'),
    'lead': (1, 'Category7', 'raw'),
    'manganese': (2, 'Category3', 'raw'),
    'mechanicalcomponents': (3, 'MechanicalComponents', 'manufactured'),
    'mechanicalequipment': (2, 'MechanicalComponents', 'manufactured'),
    'mechanicalscrap': (1, 'MechanicalComponents', 'manufactured'),
    'mercury': (3, 'Category6', 'raw'),
    'militarygradealloys': (5, 'Thermic', 'manufactured'),
    'militarysupercapacitors': (5, 'Capacitors', 'manufactured'),
    'modifiedconsumerfirmware': (2, 'EncodedFirmware', 'encoded'),
    'modifiedembeddedfirmware': (5, 'EncodedFirmware', 'encoded'),
    'molybdenum': (3, 'Category2', 'raw'),
    'nickel': (1, 'Category5', 'raw'),
    'niobium': (3, 'Category1', 'raw'),
    'opensymmetrickeys': (3, 'EncryptionFiles', 'encoded'),
    'peculiarshieldfrequencydata': (5, 'ShieldData', 'encoded'),
    'pharmaceuticalisolators': (5, 'Chemical', 'manufactured'),
    'phasealloys': (3, 'Alloys', 'manufactured'),
    'phosphorus': (1, 'Category2', 'raw'),
    'polonium': (4, 'Category6', 'raw'),
    'polymercapacitors': (4, 'Capacitors', 'manufactured'),
    'precipitatedalloys': (3, 'Thermic', 'manufactured'),
    'protoheatradiators': (5, 'Heat', 'manufactured'),
    'protolightalloys': (4, 'Alloys', 'manufactured'),
    'protoradiolicalloys': (5, 'Alloys', 'manufactured'),
    'refinedfocuscrystals': (4, 'Crystals', 'manufactured'),
    'rhenium': (1, 'Category6', 'raw'),
    'ruthenium': (4, 'Category3', 'raw'),
    'salvagedalloys': (1, 'Alloys', 'manufactured'),
    'scandatabanks': (3, 'DataArchives', 'encoded'),
    'securityfirmwarepatch': (4, 'EncodedFirmware', 'encoded'),
    'selenium': (4, 'Category4', 'raw'),
    'shielddensityreports': (3, 'ShieldData', 'encoded'),
    'shieldemitters': (2, 'Shielding', 'manufactured'),
    'shieldingsensors': (3, 'Shielding', 'manufactured'),
    'specialisedlegacyfirmware': (1, 'EncodedFirmware', 'encoded'),
    'strangewakesolutions': (3, 'WakeScans', 'encoded'),
    'sulphur': (1, 'Category3', 'raw'),
    'taggedencryptioncodes': (2, 'EncryptionFiles', 'encoded'),
    'technetium': (4, 'Category2', 'raw'),
    'tellurium': (4, 'Category5', 'raw'),
    'temperedalloys': (1, 'Thermic', 'manufactured'),
    'tg_biomechanicalconduits': (3, 'ThargoidShip', 'manufactured'),
    'tg_compositiondata': (3, 'ThargoidSite', 'encoded'),
    'tg_interdictiondata': (5, 'ThargoidShip', 'encoded'),
    'tg_propulsionelement': (5, 'ThargoidShip', 'manufactured'),
    'tg_residuedata': (4, 'ThargoidSite', 'encoded'),
    'tg_shipflightdata': (3, 'ThargoidShip', 'encoded'),
    'tg_shipsystemsdata': (4, 'ThargoidShip', 'encoded'),
    'tg_shutdowndata': (4, 'ThargoidShip', 'encoded'),
    'tg_structuraldata': (2, 'ThargoidSite', 'encoded'),
    'tg_weaponparts': (4, 'ThargoidShip', 'manufactured'),
    'tg_wreckagecomponents': (3, 'ThargoidShip', 'manufactured'),
    'thermicalloys': (4, 'Thermic', 'manufactured'),
    'tin': (3, 'Category4', 'raw'),
    'tungsten': (3, 'Category5', 'raw'),
    'uncutfocuscrystals': (2, 'Crystals', 'manufactured'),
    'unidentifiedscanarchives': (2, 'DataArchives', 'encoded'),
    'unknowncarapace': (2, 'ThargoidSite', 'manufactured'),
    'unknownenergycell': (3, 'ThargoidSite', 'manufactured'),
    'unknownenergysource': (5, 'ThargoidSite', 'manufactured'),
    'unknownorganiccircuitry': (5, 'ThargoidSite', 'manufactured'),
    'unknownshipsignature': (3, 'ThargoidShip', 'encoded'),
    'unknowntechnologycomponents': (4, 'ThargoidSite', 'manufactured'),
    'unknownwakedata': (4, 'ThargoidShip', 'encoded'),
    'unusualencryptedfiles': (1, 'EncryptionFiles', 'encoded'),
    'vanadium': (2, 'Category1', 'raw'),
    'wornshieldemitters': (1, 'Shielding', 'manufactured'),
    'yttrium': (4, 'Category1', 'raw'),
    'zinc': (2, 'Category4', 'raw'),
    'zirconium': (2, 'Category7', 'raw'),
}

DEFAULT_EXCESS_THRESHOLD = 30


class TradeSuggestion(TypedDict):
    source: str            # internal name of the material to trade away
    source_qty_used: int   # how many units of it this trade would use
    source_spare: int      # how many units of it you currently have
    missing_covered: int   # how much of the shortfall this covers
    full_cover: bool       # True if this fully covers the shortfall


def _units_needed(missing_qty: int, source_rank: int, source_group: str, target_rank: int, target_group: str) -> Optional[int]:
    """Exact source units needed to fully cover `missing_qty`, per
    EDEngineer's own formulas — None if this trade direction isn't valid."""
    rank_diff = source_rank - target_rank
    same_group = source_group == target_group
    if same_group:
        if rank_diff > 0:
            return math.ceil(missing_qty / (3 ** rank_diff))
        return (6 ** abs(rank_diff)) * missing_qty
    else:
        if rank_diff > 0:
            return 2 * math.ceil(missing_qty / (3 ** (rank_diff - 1)))
        if rank_diff == 0:
            return 6 * missing_qty
        return None  # cross-group, trading up: not possible


def find_material_trades(
    shortfalls: Dict[str, int],
    owned: Dict[str, int],
    excess_threshold: int = DEFAULT_EXCESS_THRESHOLD,
) -> Dict[str, TradeSuggestion]:
    """
    For each material you're short on (`shortfalls`: {internal_name:
    amount needed}), finds the single best real trade from a material
    you have plenty of (`owned`, count > excess_threshold, and not
    itself a shortfall) that covers as much of it as possible.

    Prefers a trade that fully covers the shortfall over a partial one,
    and same-group trades (always cheaper) over cross-group. Tracks
    consumption across shortfalls so one excess material never gets
    suggested as the source for more than it actually has spare.

    A material not in the known trade-group table, or with no valid
    covering trade at all, is simply omitted — not an error.
    """
    committed: Dict[str, int] = {}
    excess_pool = [
        sym for sym, qty in owned.items()
        if isinstance(qty, int) and qty > excess_threshold
        and sym not in shortfalls and sym in _MATERIAL_INFO
    ]

    results: Dict[str, TradeSuggestion] = {}
    for needed_sym, missing_qty in shortfalls.items():
        if not isinstance(missing_qty, int) or missing_qty <= 0 or needed_sym not in _MATERIAL_INFO:
            continue
        target_rank, target_group, target_kind = _MATERIAL_INFO[needed_sym]

        best: Optional[TradeSuggestion] = None
        for source_sym in excess_pool:
            source_rank, source_group, source_kind = _MATERIAL_INFO[source_sym]
            if source_kind != target_kind:
                continue

            needed_units = _units_needed(missing_qty, source_rank, source_group, target_rank, target_group)
            if needed_units is None or needed_units <= 0:
                continue

            spare = owned[source_sym] - committed.get(source_sym, 0)
            if spare <= 0:
                continue

            full_cover = spare >= needed_units
            units_used = needed_units if full_cover else spare
            # Proportional estimate — exact for the multiplicative (trade
            # up) formulas, a close approximation for the ceiling-based
            # (trade down) ones. Good enough for an advisor suggestion,
            # not meant to be a certified-precise calculator.
            missing_covered = missing_qty if full_cover else min(
                missing_qty, (units_used * missing_qty) // needed_units
            )
            if missing_covered <= 0:
                continue

            candidate: TradeSuggestion = {
                "source": source_sym,
                "source_qty_used": units_used,
                "source_spare": owned[source_sym],
                "missing_covered": missing_covered,
                "full_cover": full_cover,
            }

            if best is None:
                best = candidate
                continue
            # Prefer: full cover > more covered > same-group (cheaper,
            # implied by needing fewer source units) > fewer source units.
            better = (
                (candidate["full_cover"], candidate["missing_covered"], -units_used)
                > (best["full_cover"], best["missing_covered"], -best["source_qty_used"])
            )
            if better:
                best = candidate

        if best is not None:
            committed[best["source"]] = committed.get(best["source"], 0) + best["source_qty_used"]
            results[needed_sym] = best

    return results
