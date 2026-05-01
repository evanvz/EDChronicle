"""Status / general TTS phrase module."""
from edc.audio.tts_phrases import pick


class StatusPhrases:

    GAME_LOADED = [
        "Welcome back, Commander . systems online.",
        "Good to have you back, Commander . ship ready.",
        "Commander . {ship} is flight ready.",
        "Systems nominal. Welcome aboard, Commander .",
        "standing by. Good day, Commander .",
    ]

    MISSION_COMPLETE = [
        "Mission complete. {credits} credits from {faction}.",
        "Job done. {credits} credits received from {faction}.",
        "{faction} mission complete. {credits} credits awarded.",
        "Mission accomplished. {credits} credits.",
    ]

    BEING_SCANNED = [
        "We are being scanned by the enemy.",
        "Enemy can detected. They are running a check on us.",
        "External scan in progress.",
        "Enemy ship scan detected, Commander.",
    ]

    SCAN_COMPLETE = [
        "External {scan_type} scan complete.",
        "External scan finished. {scan_type}.",
        "External {scan_type} scan done.",
    ]

    MATERIALS_LOW = [
        "Low materials warning. {material} stock is depleted.",
        "{material} running low, Commander.",
        "Material alert. {material} below threshold.",
        "Stock warning. {material} is low.",
    ]

    DOCKED = [
        "Docked at {station}.",
        "Welcome to {station}.",
        "Docking complete. {station}.",
        "Ship secured at {station}.",
    ]

    UNDOCKED = [
        "Undocking from {station}.",
        "Cleared from {station}. Good flying.",
        "Leaving {station}.",
        "Undocked. Fly safe, Commander.",
    ]

    @staticmethod
    def game_loaded(commander: str, ship: str) -> str:
        return pick(StatusPhrases.GAME_LOADED,
                    commander=commander, ship=ship)

    @staticmethod
    def mission_complete(credits: int, faction: str) -> str:
        return pick(StatusPhrases.MISSION_COMPLETE,
                    credits=f"{credits:,}", faction=faction)

    @staticmethod
    def being_scanned() -> str:
        return pick(StatusPhrases.BEING_SCANNED)

    @staticmethod
    def scan_complete(scan_type: str = "") -> str:
        return pick(StatusPhrases.SCAN_COMPLETE, scan_type=scan_type)

    @staticmethod
    def materials_low(material: str) -> str:
        return pick(StatusPhrases.MATERIALS_LOW, material=material)

    @staticmethod
    def docked(station: str) -> str:
        return pick(StatusPhrases.DOCKED, station=station)

    @staticmethod
    def undocked(station: str) -> str:
        return pick(StatusPhrases.UNDOCKED, station=station)
