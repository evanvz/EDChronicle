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

    SCAN_COMPLETE = [
        "External {scan_type} scan complete.",
        "External scan finished. {scan_type}.",
        "External {scan_type} scan done.",
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
    def scan_complete(scan_type: str = "") -> str:
        return pick(StatusPhrases.SCAN_COMPLETE, scan_type=scan_type)

