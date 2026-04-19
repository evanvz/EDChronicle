"""Exobiology TTS phrase module."""
from edc.audio.tts_phrases import pick


class ExobiologyPhrases:

    SCAN_FIRST = [
        "First scan logged. One of three.",
        "Biological contact logged. First of three.",
        "Initial scan complete. Two more required.",
        "Log entry recorded. Two scans remaining.",
    ]

    SCAN_SECOND = [
        "Second scan complete. One more required.",
        "Two of three samples collected.",
        "Sample two confirmed. Final scan needed.",
        "Halfway done. One scan remaining.",
    ]

    SCAN_THIRD = [
        "Third scan complete. All samples collected.",
        "Final sample taken. Ready for analysis.",
        "Three of three. Proceed to analyse.",
        "All samples gathered. Analysis ready.",
    ]

    SCAN_COMPLETE = [
        "Analysis complete. Safe to move to next organism.",
        "Fully catalogued. You may proceed.",
        "Three samples recorded. Analysis done.",
        "Biological scan complete. Move to next site.",
    ]

    SELL_DATA = [
        "Biological data sold. {count} species. {value} million credits earned.",
        "Exobiology data uploaded. {value} million credits received.",
        "{count} species sold for {value} million credits.",
        "Data sold. {value} million from {count} organisms.",
    ]

    HIGH_VALUE_SPECIES = [
        "High value organism. {species}. Worth {value} million credits.",
        "High value biological contact. {species} — {value} million estimated.",
        "{species} — exceptional value. {value} million credits.",
        "Notable organism. {species}. Approximately {value} million credits.",
    ]

    SCAN_CODEX = [
        "Codex scan complete. {species} identified.",
        "{species} — codex entry recorded.",
        "Biological contact. {species}. Codex scan logged.",
        "{species} confirmed via codex scan.",
    ]

    CCR_DISTANCE_REACHED = [
        "Distance reached. Safe to take next sample.",
        "Minimum distance met. Next sample viable.",
        "You may take the next sample. Distance cleared.",
        "Separation distance achieved. Next sample ready.",
        "distance met. Proceed to next sample.",
    ]

    CCR_TOO_CLOSE = [
        "Too close. Move further from last scan point.",
        "distance lost. Move away from previous sample.",
        "Warning. Inside minimum scan distance.",
        "You have moved too close. Maintain required separation.",
    ]

    STAGE_MAP = {
        "Log":         SCAN_FIRST,
        "Sample":      SCAN_SECOND,
        "SampleFinal": SCAN_THIRD,
        "Analyse":     SCAN_COMPLETE,
        "Codex":       SCAN_CODEX,
    }

    @staticmethod
    def scan_progress(stage: str, species: str) -> str:
        pool = ExobiologyPhrases.STAGE_MAP.get(
            stage, ExobiologyPhrases.SCAN_FIRST
        )
        return pick(pool, species=species)

    @staticmethod
    def ccr_distance_reached() -> str:
        return pick(ExobiologyPhrases.CCR_DISTANCE_REACHED)

    @staticmethod
    def ccr_too_close() -> str:
        return pick(ExobiologyPhrases.CCR_TOO_CLOSE)

    @staticmethod
    def sell_data(earnings: int, species_count: int) -> str:
        return pick(ExobiologyPhrases.SELL_DATA,
                    value=earnings // 1_000_000,
                    count=species_count)

    @staticmethod
    def high_value_species(species: str, value: int) -> str:
        return pick(ExobiologyPhrases.HIGH_VALUE_SPECIES,
                    species=species, value=value // 1_000_000)
