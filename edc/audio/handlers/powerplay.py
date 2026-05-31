"""PowerPlay TTS phrase module."""
from edc.audio.tts_phrases import pick


class PowerPlayPhrases:

    PP_REINFORCEMENT = [
        "Reinforcement system. {power} controls here.",
        "{power} space. Reinforcement target.",
        "Friendly system. {power} — reinforcement available.",
        "{power} territory. We can reinforce here.",
    ]

    PP_REINFORCEMENT_FORTIFIED = [
        "Reinforcement system. {power} stronghold.",
        "{power} fortified system. Reinforcement target.",
        "Friendly stronghold. {power} controls here.",
        "{power} stronghold. Reinforce and defend.",
    ]

    PP_UNDERMINING = [
        "Undermining system. {power} controls here.",
        "{power} territory. Undermining target.",
        "Enemy controlled. {power}. Undermining available.",
        "{power} system. Undermining possible.",
    ]

    PP_UNDERMINING_FORTIFIED = [
        "Enemy stronghold. {power} has fortified this system.",
        "{power} stronghold. High resistance — undermining target.",
        "Fortified undermining system. {power} controls here.",
        "{power} has fortified this system. Undermining available.",
    ]

    PP_ACQUISITION = [
        "Acquisition target. Uncontrolled system.",
        "Uncontrolled space. Acquisition available.",
        "No controlling power. Acquisition system.",
        "Acquisition target. System is open.",
    ]

    PP_ACQUISITION_EXPANSION = [
        "Expansion system. Acquisition in progress.",
        "Active acquisition system. Expansion underway.",
        "Expansion target. Acquisition available.",
    ]

    PP_ACQUISITION_CONTESTED = [
        "Contested acquisition target.",
        "Contested system. Acquisition available.",
        "PowerPlay contest in progress. Acquisition target.",
        "Contested space. Multiple powers competing.",
    ]

    PP_NEUTRAL = [
        "Neutral space. No PowerPlay presence.",
        "Uncontested system.",
        "No PowerPlay control here.",
        "Neutral territory.",
    ]

    PP_POWER_PRESENT = [
        "{power} has presence here. Not the controlling faction.",
        "Our power active in this system. Operating without control.",
        "{power} operating here. No system control.",
    ]

    PP_UNDERMINING_PRESENT = [
        "{power} is present. Undermining possible.",
        "Our power has presence here. Undermining viable.",
        "{power} active in this system. Undermining target.",
    ]

    PP_NOT_PRESENT = [
        "{power} has no presence in this system.",
        "Our power is not active here.",
        "{power} not present. No undermining opportunity.",
    ]

    @staticmethod
    def pp_space(power: str, pp_state: str, pledged: str) -> str:
        """Generate PP arrival phrase based on controlling power, state and allegiance."""
        if not power or power.strip().lower() in ("", "unoccupied"):
            state_low = str(pp_state or "").lower()
            if "contested" in state_low:
                return pick(PowerPlayPhrases.PP_ACQUISITION_CONTESTED)
            if "expansion" in state_low:
                return pick(PowerPlayPhrases.PP_ACQUISITION_EXPANSION)
            if state_low and state_low not in ("uncontrolled",):
                return pick(PowerPlayPhrases.PP_NEUTRAL)
            return pick(PowerPlayPhrases.PP_ACQUISITION)

        is_friendly = bool(pledged and power.strip().lower() == pledged.strip().lower())
        state_low = str(pp_state or "").lower()
        is_fortified = "fortified" in state_low or "stronghold" in state_low
        is_contested = "contested" in state_low
        is_expansion = "expansion" in state_low

        if is_contested:
            return pick(PowerPlayPhrases.PP_ACQUISITION_CONTESTED)

        if is_expansion:
            return pick(PowerPlayPhrases.PP_ACQUISITION_EXPANSION)

        if is_friendly:
            if is_fortified:
                return pick(PowerPlayPhrases.PP_REINFORCEMENT_FORTIFIED, power=power)
            return pick(PowerPlayPhrases.PP_REINFORCEMENT, power=power)
        else:
            if is_fortified:
                return pick(PowerPlayPhrases.PP_UNDERMINING_FORTIFIED, power=power)
            return pick(PowerPlayPhrases.PP_UNDERMINING, power=power)

    @staticmethod
    def pp_present(power: str) -> str:
        """Pledged power is active in system but does not control it."""
        return pick(PowerPlayPhrases.PP_POWER_PRESENT, power=power)

    @staticmethod
    def pp_undermining_present(power: str) -> str:
        return pick(PowerPlayPhrases.PP_UNDERMINING_PRESENT, power=power)

    @staticmethod
    def pp_not_present(power: str) -> str:
        return pick(PowerPlayPhrases.PP_NOT_PRESENT, power=power)
