# State Write Map

## last_event
- **File:** edc/core/event_engine.py
  - **Line:** 80: `self.state.last_event = name`

## system
- **File:** edc/core/event_engine.py
  - **Line:** 83: `self.state.system = new_sys`
- **File:** edc/core/event_engine.py
  - **Line:** 100: `self.state.system = target or self.state.system`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 12: `engine.state.system = new_sys or engine.state.system`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 29: `engine.state.system = sys_name`

## bodies
- **File:** edc/core/event_engine.py
  - **Line:** 86: `self.state.bodies.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 101: `self.state.bodies.clear()`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 30: `engine.state.bodies.clear()`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 43: `engine.state.bodies[body_name] = event`

## exo
- **File:** edc/core/event_engine.py
  - **Line:** 87: `self.state.exo.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 102: `self.state.exo.clear()`

## body_id_to_name
- **File:** edc/core/event_engine.py
  - **Line:** 88: `self.state.body_id_to_name.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 103: `self.state.body_id_to_name.clear()`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 44: `engine.state.body_id_to_name[body_id] = body_name`

## bio_signals
- **File:** edc/core/event_engine.py
  - **Line:** 89: `self.state.bio_signals.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 104: `self.state.bio_signals.clear()`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 45: `engine.state.bio_signals[body] = len(bio)`

## bio_genuses
- **File:** edc/core/event_engine.py
  - **Line:** 90: `self.state.bio_genuses.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 105: `self.state.bio_genuses.clear()`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 46: `engine.state.bio_genuses[body] = sorted(set(genuses))`

## geo_signals
- **File:** edc/core/event_engine.py
  - **Line:** 91: `self.state.geo_signals.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 106: `self.state.geo_signals.clear()`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 47: `engine.state.geo_signals[body] = len(geo)`

## non_body_count
- **File:** edc/core/event_engine.py
  - **Line:** 92: `self.state.non_body_count = None`
- **File:** edc/core/event_engine.py
  - **Line:** 107: `self.state.non_body_count = None`

## system_signals
- **File:** edc/core/event_engine.py
  - **Line:** 93: `self.state.system_signals = []`
- **File:** edc/core/event_engine.py
  - **Line:** 108: `self.state.system_signals = []`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 48: `engine.state.system_signals.append(cls)`

## external_pois
- **File:** edc/core/event_engine.py
  - **Line:** 94: `self.state.external_pois = []`
- **File:** edc/core/event_engine.py
  - **Line:** 109: `self.state.external_pois = []`

## system_body_count
- **File:** edc/core/event_engine.py
  - **Line:** 95: `self.state.system_body_count = None`
- **File:** edc/core/event_engine.py
  - **Line:** 110: `self.state.system_body_count = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 49: `engine.state.system_body_count = bc`

## system_allegiance
- **File:** edc/core/event_engine.py
  - **Line:** 96: `self.state.system_allegiance = None`
- **File:** edc/core/event_engine.py
  - **Line:** 111: `self.state.system_allegiance = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 50: `engine.state.system_allegiance = ...`

## system_government
- **File:** edc/core/event_engine.py
  - **Line:** 97: `self.state.system_government = None`
- **File:** edc/core/event_engine.py
  - **Line:** 112: `self.state.system_government = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 51: `engine.state.system_government = ...`

## system_economy
- **File:** edc/core/event_engine.py
  - **Line:** 98: `self.state.system_economy = None`
- **File:** edc/core/event_engine.py
  - **Line:** 113: `self.state.system_economy = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 52: `engine.state.system_economy = ...`

## system_security
- **File:** edc/core/event_engine.py
  - **Line:** 99: `self.state.system_security = None`
- **File:** edc/core/event_engine.py
  - **Line:** 114: `self.state.system_security = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 53: `engine.state.system_security = ...`

## population
- **File:** edc/core/event_engine.py
  - **Line:** 100: `self.state.population = None`
- **File:** edc/core/event_engine.py
  - **Line:** 115: `self.state.population = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 54: `engine.state.population = ...`

## controlling_faction
- **File:** edc/core/event_engine.py
  - **Line:** 101: `self.state.controlling_faction = None`
- **File:** edc/core/event_engine.py
  - **Line:** 116: `self.state.controlling_faction = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 55: `engine.state.controlling_faction = ...`

## factions
- **File:** edc/core/event_engine.py
  - **Line:** 102: `self.state.factions = []`
- **File:** edc/core/event_engine.py
  - **Line:** 117: `self.state.factions = []`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 56: `engine.state.factions = ...`

## system_controlling_power
- **File:** edc/core/event_engine.py
  - **Line:** 103: `self.state.system_controlling_power = None`
- **File:** edc/core/event_engine.py
  - **Line:** 118: `self.state.system_controlling_power = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 57: `engine.state.system_controlling_power = ...`

## system_powerplay_state
- **File:** edc/core/event_engine.py
  - **Line:** 104: `self.state.system_powerplay_state = None`
- **File:** edc/core/event_engine.py
  - **Line:** 119: `self.state.system_powerplay_state = None`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 58: `engine.state.system_powerplay_state = ...`

## system_powers
- **File:** edc/core/event_engine.py
  - **Line:** 105: `self.state.system_powers = []`
- **File:** edc/core/event_engine.py
  - **Line:** 120: `self.state.system_powers = []`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 59: `engine.state.system_powers = ...`

## system_powerplay_conflict_progress
- **File:** edc/core/event_engine.py
  - **Line:** 106: `self.state.system_powerplay_conflict_progress = {}`
- **File:** edc/core/event_engine.py
  - **Line:** 121: `self.state.system_powerplay_conflict_progress = {}`
- **File:** edc/engine/handlers/exploration.py
  - **Line:** 60: `engine.state.system_powerplay_conflict_progress = ...`

## pp_enemy_alerts
- **File:** edc/core/event_engine.py
  - **Line:** 107: `self.state.pp_enemy_alerts.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 122: `self.state.pp_enemy_alerts.clear()`

## combat_contacts
- **File:** edc/core/event_engine.py
  - **Line:** 108: `self.state.combat_contacts.clear()`
- **File:** edc/core/event_engine.py
  - **Line:** 123: `self.state.combat_contacts.clear()`

## combat_current_key
- **File:** edc/core/event_engine.py
  - **Line:** 109: `self.state.combat_current_key = ""`
- **File:** edc/core/event_engine.py
  - **Line:** 124: `self.state.combat_current_key = ""`

## cargo_count
- **File:** edc/core/event_engine.py
  - **Line:** 110: `self.state.cargo_count = event.get("Count")`

## limpets
- **File:** edc/core/event_engine.py
  - **Line:** 111: `self.state.limpets = limpets`

## last_body
- **File:** edc/engine/handlers/exobio.py
  - **Line:** 6: `engine.state.last_body = body`

## last_organic_scan
- **File:** edc/engine/handlers/exobio.py
  - **Line:** 8: `engine.state.last_organic_scan = event`

## last_organic_value
- **File:** edc/engine/handlers/exobio.py
  - **Line:** 10: `engine.state.last_organic_value = val`

## session_exobio_earnings
- **File:** edc/engine/handlers/exobio.py
  - **Line:** 12: `engine.state.session_exobio_earnings += total`

## session_voucher_earnings
- **File:** edc/engine/handlers/misc.py
  - **Line:** 6: `engine.state.session_voucher_earnings += amt`

## community_goals
- **File:** edc/engine/handlers/misc.py
  - **Line:** 9: `engine.state.community_goals[cgid] = rec`

## last_target_ship
- **File:** edc/engine/handlers/misc.py
  - **Line:** 12: `engine.state.last_target_ship = tgt`
                                                                                                                                                                                                                                                                                                               
## last_target_pilot
- **File:** edc/engine/handlers/misc.py
  - **Line:** 13: `engine.state.last_target_pilot = pilot`

## power
- **File:** edc/engine/handlers/powerplay.py
  - **Line:** 5: `engine.state.power = event.get("Power")`

## power_state
- **File:** edc/engine/handlers/powerplay.py
  - **Line:** 6: `engine.state.power_state = event.get("State")`

## power_merits
- **File:** edc/engine/handlers/powerplay.py
  - **Line:** 8: `engine.state.power_merits = merit`

## power_rank
- **File:** edc/engine/handlers/powerplay.py
  - **Line:** 10: `engine.state.power_rank = rank`
