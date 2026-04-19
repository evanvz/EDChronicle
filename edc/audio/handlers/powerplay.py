"""PowerPlay TTS phrase module."""
from edc.audio.tts_phrases import pick


class PowerPlayPhrases:

    PP_FRIENDLY = [
        "Friendly PowerPlay space. {power} controls this system.",
        "{power} territory. We are safe here.",
        "Friendly space. {power} is our power.",
        "PowerPlay friendly. {power} system.",
        "We are in {power} space. All clear.",
    ]

    PP_ENEMY = [
        "Caution. Enemy PowerPlay territory. {power} controls this system.",
        "Enemy space. {power} controls here. Stay alert.",
        "{power} territory. Expect opposition.",
        "Hostile PowerPlay zone. {power}.",
        "Enemy space, Commander. {power} is our opposition here.",
        "Warning. {power} controlled system. Eyes open.",
    ]

    PP_NEUTRAL = [
        "Neutral space. No PowerPlay presence.",
        "Uncontested system.",
        "No PowerPlay control here.",
        "Neutral territory.",
    ]

    PP_FORTIFIED = [
        "Caution. Enemy stronghold. {power} has fortified this system.",
        "{power} stronghold detected. High resistance expected.",
        "Enemy fortified system. {power} controls here.",
        "This system is a {power} stronghold. Proceed with caution.",
    ]

    PP_EXPLOITED = [
        "Entering {power} exploited system.",
        "{power} exploited space. Stay alert.",
        "This system is exploited by {power}.",
    ]

    PP_POWER_PRESENT = [
        "{power} has presence here. Not the controlling faction.",
        "Our power active in this system. Operating without control.",
        "{power} operating here. No system control.",
    ]

    PP_CONTESTED = [
        "Contested system. PowerPlay conflict in progress.",
        "This system is under PowerPlay contest.",
        "Contested space. Multiple powers present.",
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
        """Generate PP arrival phrase based on state and allegiance."""
        if not power or power.lower() in ("", "unoccupied"):
            return pick(PowerPlayPhrases.PP_NEUTRAL)

        is_friendly = bool(
            pledged and power.strip().lower() == pledged.strip().lower()
        )
        state_low = str(pp_state or "").lower()

        if "fortified" in state_low or "stronghold" in state_low:
            if not is_friendly:
                return pick(PowerPlayPhrases.PP_FORTIFIED, power=power)

        if "contested" in state_low:
            return pick(PowerPlayPhrases.PP_CONTESTED)

        if is_friendly:
            return pick(PowerPlayPhrases.PP_FRIENDLY, power=power)
        else:
            return pick(PowerPlayPhrases.PP_ENEMY, power=power)

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

    @staticmethod
    def pp_neutral() -> str:
        return pick(PowerPlayPhrases.PP_NEUTRAL)
