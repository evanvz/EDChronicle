"""Combat TTS phrase module."""
from edc.audio.tts_phrases import pick


class CombatPhrases:

    BOUNTY = [
        "Bounty received. {credits} credits from {faction}.",
        "{faction} issued {credits} credit bounty. Received.",
        "Bounty of {credits} credits received.",
        "Combat voucher received. {credits}",
    ]

    INTERDICTION = [
        "Interdiction detected. Prepare for evasive manoeuvres.",
        "Mass lock detected. Being pulled from super cruise.",
        "Hostile interdiction incoming. Evade or submit.",
        "Frame shift interference. Interdiction in progress.",
        "Someone is pulling us out. Engage evasion.",
    ]

    ESCAPE_INTERDICTION = [
        "Interdiction escaped. Back in super cruise.",
        "Evasion successful. We are clear.",
        "Interdiction broken. Resuming cruise.",
        "Clear of gravity well. Good flying, Commander.",
    ]

    UNDER_ATTACK = [
        "Taking fire, Commander.",
        "Hull under attack.",
        "Incoming fire detected.",
        "Combat alert. Taking damage.",
    ]

    KILL_BOND = [
        "Kill bond awarded received. {credits} credits from {faction}.",
        "Combat bond from {faction}. {credits} credits received.",
        "{credits} credits received.",
    ]

    NPC_CHALLENGE = [
        "Going to try his luck. Let's show him who's boss around here.",
        "They picked the wrong ship to tangle with today.",
        "Threatening us? Bold move. Let's remind them why that's a mistake.",
        "Noted. Arming up. Let's see how brave they really are.",
        "They want a fight. Happy to oblige.",
        "Copy that. Targeting solutions ready, Commander.",
    ]

    WANTED_TARGET_SCAN = [
        "There's a bounty on that one. Let's collect.",
        "Wanted. They're worth something to us dead.",
        "That pilot's got a price on their head. Time to cash in.",
        "Bounty confirmed. Permission to engage, Commander?",
        "That one's wanted. Let's make this count.",
        "Good news, Commander. That target's worth credits.",
    ]

    POWERPLAY_ENEMY_SCAN = [
        "Rival power vessel. No bounty, but they're fair game here, Commander.",
        "Opposing power detected in our territory. Permission to engage?",
        "That's an enemy of the cause. No bounty on them, but push them back.",
        "Rival colours. This is our space -- let's remind them.",
        "Hostile power signature. Contest them, Commander.",
    ]

    HIGH_VALUE_CONTACT_SCAN = [
        "Notable contact, Commander. Worth your attention.",
        "High-threat signature detected. Stay sharp.",
        "That one's dangerous. Your call, Commander.",
        "Elite-rated contact in the area. Proceed with caution.",
        "Combat-capable target nearby. Handle as needed.",
    ]

    @staticmethod
    def ship_targeted(ship: str, rank: str, power: str, is_enemy: bool,
                      wanted: bool, bounty: int, is_high_value: bool = False,
                      engage_risk: str = "") -> str:
        """Compose a full target assessment phrase from available attributes."""
        parts = [ship or "Unknown ship"]
        if rank:
            parts.append(rank + ".")
        if is_enemy and power:
            parts.append(f"{power} faction. Enemy.")
        elif power:
            parts.append(f"{power}.")
        if is_high_value:
            parts.append("High value target.")
        if wanted:
            if bounty:
                parts.append(f"Wanted. Bounty {bounty:,} credits.")
            else:
                parts.append("Wanted.")
        elif bounty:
            parts.append(f"Bounty {bounty:,} credits.")
        if engage_risk == "safe":
            parts.append("Clear to engage.")
        elif engage_risk == "caution":
            parts.append("Caution -- anarchy space, not guaranteed near a port.")
        elif engage_risk == "unknown":
            parts.append("Engaging will likely draw a bounty.")
        return " ".join(parts)

    @staticmethod
    def bounty(credits: int, faction: str) -> str:
        return pick(CombatPhrases.BOUNTY,
                    credits=f"{credits:,}", faction=faction)

    @staticmethod
    def interdiction() -> str:
        return pick(CombatPhrases.INTERDICTION)

    @staticmethod
    def escape_interdiction() -> str:
        return pick(CombatPhrases.ESCAPE_INTERDICTION)

    @staticmethod
    def under_attack() -> str:
        return pick(CombatPhrases.UNDER_ATTACK)

    @staticmethod
    def kill_bond(credits: int, faction: str) -> str:
        return pick(CombatPhrases.KILL_BOND,
                    credits=f"{credits:,}", faction=faction)

    @staticmethod
    def npc_challenge() -> str:
        return pick(CombatPhrases.NPC_CHALLENGE)

    @staticmethod
    def wanted_target_scan() -> str:
        return pick(CombatPhrases.WANTED_TARGET_SCAN)

    @staticmethod
    def powerplay_enemy_scan() -> str:
        return pick(CombatPhrases.POWERPLAY_ENEMY_SCAN)

    @staticmethod
    def high_value_contact_scan() -> str:
        return pick(CombatPhrases.HIGH_VALUE_CONTACT_SCAN)
