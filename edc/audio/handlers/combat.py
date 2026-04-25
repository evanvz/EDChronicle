"""Combat TTS phrase module."""
from edc.audio.tts_phrases import pick


class CombatPhrases:

    PASS_TARGET = [
        "Not a target ship.",
        "Not worth engaging that ship.",
        "Pass this target ship.",
        "Low priority target ship.",
        "No threat from that ship.",
    ]

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

    SCANNED = [
        "We've been scanned. {scan_type} check.",
        "External scan detected. {scan_type}.",
        "We just got scanned. {scan_type}.",
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

    @staticmethod
    def ship_targeted(ship: str, rank: str, power: str, is_enemy: bool,
                      wanted: bool, bounty: int) -> str:
        """Compose a full target assessment phrase from available attributes."""
        parts = [ship or "Unknown ship"]
        if rank:
            parts.append(rank + ".")
        if is_enemy and power:
            parts.append(f"{power} faction. Enemy.")
        elif power:
            parts.append(f"{power}.")
        if wanted:
            if bounty:
                parts.append(f"Wanted. Bounty {bounty:,} credits.")
            else:
                parts.append("Wanted.")
        elif bounty:
            parts.append(f"Bounty {bounty:,} credits.")
        return " ".join(parts)

    @staticmethod
    def pass_target() -> str:
        return pick(CombatPhrases.PASS_TARGET)

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
    def scanned(scan_type: str = "") -> str:
        return pick(CombatPhrases.SCANNED, scan_type=scan_type)

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
