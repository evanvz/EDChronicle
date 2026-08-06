"""Rank-index -> display-name tables for the Rank/Progress journal events.
Verified against the community Journal Manual (elite-journal.readthedocs.io).
Combat/Trade/Explore/CQC/Soldier/Exobiologist top out at "Elite" (index 8)
then extend into Elite I-V (indices 9-13, added alongside Odyssey); Empire/
Federation have their own fixed ladder with no Elite tier.
"""
from __future__ import annotations

_ELITE_TIERS = ["I", "II", "III", "IV", "V"]

RANK_NAMES = {
    "Combat": ["Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
               "Master", "Dangerous", "Deadly", "Elite"],
    "Trade": ["Penniless", "Mostly Penniless", "Peddler", "Dealer", "Merchant",
              "Broker", "Entrepreneur", "Tycoon", "Elite"],
    "Explore": ["Aimless", "Mostly Aimless", "Scout", "Surveyor", "Explorer",
                "Pathfinder", "Ranger", "Pioneer", "Elite"],
    "CQC": ["Helpless", "Mostly Helpless", "Amateur", "Semi Professional",
            "Professional", "Champion", "Hero", "Legend", "Elite"],
    "Soldier": ["Defenceless", "Mostly Defenceless", "Rookie", "Soldier",
                "Gunslinger", "Warrior", "Gladiator", "Deadeye", "Elite"],
    "Exobiologist": ["Directionless", "Mostly Directionless", "Compiler",
                      "Collector", "Cataloguer", "Taxonomist", "Ecologist",
                      "Geneticist", "Elite"],
    "Empire": ["None", "Outsider", "Serf", "Master", "Squire", "Knight", "Lord",
               "Baron", "Viscount", "Count", "Earl", "Marquis", "Duke", "Prince", "King"],
    "Federation": ["None", "Recruit", "Cadet", "Midshipman", "Petty Officer",
                   "Chief Petty Officer", "Warrant Officer", "Ensign", "Lieutenant",
                   "Lt. Commander", "Post Commander", "Post Captain", "Rear Admiral",
                   "Vice Admiral", "Admiral"],
}


def rank_name(category: str, index: int) -> str:
    names = RANK_NAMES.get(category)
    if not names or not isinstance(index, int) or index < 0:
        return f"R{index}"
    if index < len(names):
        return names[index]
    if names[-1] == "Elite":
        tier = index - (len(names) - 1)
        if 1 <= tier <= len(_ELITE_TIERS):
            return f"Elite {_ELITE_TIERS[tier - 1]}"
    return f"R{index}"
