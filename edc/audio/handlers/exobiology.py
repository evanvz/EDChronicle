"""Exobiology TTS phrase module."""
from edc.audio.tts_phrases import pick


class ExobiologyPhrases:

    SCAN_FIRST = [
        "First scan logged. One of three.",
        "Biological contact logged. First of three.",
        "Initial scan complete. Two more required.",
        "Log entry recorded. Two scans remaining.",
        "{species} — first sample logged. Two to go.",
        "First reading on {species}. Two more needed.",
        "Got our first sample of {species}, Commander.",
    ]

    SCAN_SECOND = [
        "Second scan complete. One more required.",
        "Two of three samples collected.",
        "Sample two confirmed. Final scan needed.",
        "Halfway done. One scan remaining.",
        "{species} — second sample down. One to go.",
        "Two samples on {species} now. Last one's up to you.",
        "Almost there with {species}, Commander.",
    ]

    SCAN_THIRD = [
        "Third scan complete. All samples collected.",
        "Final sample taken. Ready for analysis.",
        "Three of three. Proceed to analyse.",
        "All samples gathered. Analysis ready.",
        "That's the set, Commander. Run the analysis.",
        "{species} — full set collected. Ready to analyse.",
        "Third and final sample of {species} logged.",
        "That's {species} done, Commander. Analyse when ready.",
    ]

    SCAN_COMPLETE = [
        "Analysis complete. Safe to move to next organism.",
        "Fully catalogued. You may proceed.",
        "Three samples recorded. Analysis done.",
        "Biological scan complete. Move to next site.",
        "{species} fully catalogued, Commander.",
        "That's {species} logged for good. Move on when ready.",
        "Analysis on {species} complete. Nicely done.",
    ]

    SELL_DATA = [
        "Biological data sold. {count} species. {value} million credits earned.",
        "Exobiology data uploaded. {value} million credits received.",
        "{count} species sold for {value} million credits.",
        "Data sold. {value} million from {count} organisms.",
        "Not bad, Commander. {value} million for {count} species.",
        "{count} species logged and sold, {value} million richer for it.",
        "That data was worth the trip — {value} million for {count} species.",
        "Vista Genomics just paid {value} million for {count} species, Commander.",
    ]

    SCAN_CODEX = [
        "Codex scan complete. {species} identified.",
        "{species} — codex entry recorded.",
        "Biological contact. {species}. Codex scan logged.",
        "{species} confirmed via codex scan.",
        "{species}. Nice find for the codex, Commander.",
        "Got {species} logged in the codex now.",
        "{species} — another one for the books.",
    ]

    CCR_DISTANCE_REACHED = [
        "Distance reached. Safe to take next sample.",
        "Minimum distance met. Next sample viable.",
        "You may take the next sample. Distance cleared.",
        "Separation distance achieved. Next sample ready.",
        "Minimum distance re-established. Proceed to next sample.",
        "Clear to sample again, Commander.",
        "Back to a safe distance. Go ahead.",
    ]

    CCR_TOO_CLOSE = [
        "Too close. Move further from last scan point.",
        "Move away from the previous sample point.",
        "Warning. Inside minimum scan distance.",
        "You have moved too close. Maintain required separation.",
        "Back off a bit, Commander — too close to the last sample.",
        "Give it more room. You're inside the minimum distance.",
        "Step back, Commander. Too close for a clean sample.",
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
