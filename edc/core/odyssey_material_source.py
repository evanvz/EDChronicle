"""Where an Odyssey on-foot material can come from besides looting.

Bartenders barter three of the four on-foot asset groups (Chemicals,
Circuits, Tech) for other assets in the same group — Data, and the
one-off Item/Consumable groups (schematics, samples, grenades, etc.),
are not barterable and can only be obtained by looting/missions.

Group data sourced from EDEngineer (https://github.com/msarilar/EDEngineer,
MIT licensed), EDEngineer/Resources/Data/entryData.json, Kind=OdysseyIngredient
entries, current as of that repo's master branch in Aug 2026.
"""
from __future__ import annotations

# {internal_name: Group} — only the three barterable groups are listed;
# anything not in here (Data, Item, Consumable) is loot/mission only.
_BARTERABLE_ODYSSEY_MATERIALS = {
    'aerogel': 'Chemicals',
    'chemicalcatalyst': 'Chemicals',
    'chemicalsuperbase': 'Chemicals',
    'epinephrine': 'Chemicals',
    'epoxyadhesive': 'Chemicals',
    'graphene': 'Chemicals',
    'oxygenicbacteria': 'Chemicals',
    'phneutraliser': 'Chemicals',
    'rdx': 'Chemicals',
    'viscoelasticpolymer': 'Chemicals',
    'circuitboard': 'Circuits',
    'circuitswitch': 'Circuits',
    'electricalfuse': 'Circuits',
    'electricalwiring': 'Circuits',
    'electromagnet': 'Circuits',
    'ionbattery': 'Circuits',
    'metalcoil': 'Circuits',
    'microelectrode': 'Circuits',
    'microsupercapacitor': 'Circuits',
    'microtransformer': 'Circuits',
    'motor': 'Circuits',
    'opticalfibre': 'Circuits',
    'carbonfibreplating': 'Tech',
    'encryptedmemorychip': 'Tech',
    'memorychip': 'Tech',
    'microhydraulics': 'Tech',
    'microthrusters': 'Tech',
    'opticallens': 'Tech',
    'scrambler': 'Tech',
    'titaniumplating': 'Tech',
    'transmitter': 'Tech',
    'tungstencarbide': 'Tech',
    'weaponcomponent': 'Tech',
}


def is_bartender_tradeable(symbol: str) -> bool:
    return symbol.lower() in _BARTERABLE_ODYSSEY_MATERIALS
