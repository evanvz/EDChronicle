"""Exploration TTS phrase module."""
from edc.audio.tts_phrases import pick


class ExplorationPhrases:

    FSD_JUMP = [
        "Entering system",
    ]

    IN_SYSTEM = [
        "Currently in {system}.",
        "Location: {system}.",
        "{system} system.",
        "In {system}.",
    ]

    ARRIVED = [
        "Jump complete.",
        "Arrived.",
        "FSD cooldown.",
        "System entry.",
        "Well, here we are.",
        "Made it in one piece, Commander.",
    ]

    VALUABLE_BODIES_SUMMARY = [
        "{count} high value planets in system.",
        "Cartographic alert. {count} high value bodies detected.",
        "{count} bodies worth mapping in this system.",
        "System contains {count} high value planets.",
        "{count} bodies here are worth the detour, Commander.",
    ]

    FSS_COMPLETE = [
        "Full system scan complete. {bodies} bodies catalogued.",
        "Honk complete. {bodies} bodies in this system.",
        "Discovery scan finished. {bodies} bodies detected.",
        "{bodies} bodies found. Full system scan complete.",
        "Scan's done. {bodies} on the board.",
    ]

    FIRST_DISCOVERY = [
        "First discovery. {body} has never been mapped.",
        "Uncharted body detected. {body} — first discovery.",
        "You are the first to discover {body}.",
        "{body} — no prior records. First discovery detected.",
        "New discovery. {body} is uncharted territory.",
        "Nobody's been here before us. {body} — nice find, Commander.",
    ]

    FIRST_MAPPED = [
        "First mapping. {body} — you are the first to surface scan this world.",
        "{body} — first surface scan complete. Bonus credits incoming.",
        "First cartographic record. {body} has never been mapped before.",
        "{body} — first mapping confirmed.",
        "Mapped and logged, Commander. Not bad for a day's work.",
    ]

    FIRST_FOOTFALL = [
        "First footfall. {body} — you are the first to set foot on this world.",
        "{body} — first footfall confirmed. Historic moment, Commander.",
        "No prior landings recorded. {body} — first footfall.",
        "{body} — you are the first person to stand here.",
        "First boots on the ground, Commander. Try not to trip.",
    ]

    BIO_SIGNALS = [
        "Biological signals detected.",
        "Bio signals on this planet.",
        "Life signs detected.",
        "Biological activity detected.",
    ]

    GEO_SIGNALS = [
        "Geological signals detected.",
        "Geo signals on this planet.",
        "Geological activity detected.",
    ]

    GUARDIAN_SIGNALS = [
        "Guardian signal detected. {count} on planet.",
        "{count} Guardian signal on planet.",
        "Ancient technology present. {count} Guardian signal.",
    ]

    GUARDIAN_SIGNALS_MULTIPLE = [
        "{count} Guardian signals detected.",
        "Multiple Guardian signals. {count} on planet.",
        "Ancient technology detected. {count} Guardian signals.",
    ]

    GUARDIAN_SIGNALS_UNCHARTED = [
        "Uncharted Guardian signals detected. This system is not in the farming guide. Possible new site.",
        "Guardian signals on an uncharted body. {count} signal. Consider logging this location.",
        "Ancient technology detected in an unknown system. {count} Guardian signal. Worth investigating.",
    ]

    GUARDIAN_SIGNALS_UNCHARTED_MULTIPLE = [
        "Uncharted Guardian signals. {count} detected. This system is not in the farming guide.",
        "{count} Guardian signals on an uncharted body. Possible undiscovered site.",
        "Multiple Guardian signals in an unknown system. {count} detected. Consider logging this location.",
    ]

    THARGOID_SIGNALS = [
        "Thargoid signal detected. {count} on planet.",
        "{count} Thargoid signal. Stay alert, Commander.",
        "Non-human signal detected. {count} Thargoid signal.",
    ]

    THARGOID_SIGNALS_MULTIPLE = [
        "{count} Thargoid signals detected. Stay alert.",
        "Multiple Thargoid signals. {count} on planet.",
        "Non-human signatures detected. {count} Thargoid signals.",
    ]

    HUMAN_SIGNALS = [
        "Human signals detected.",
        "Human presence on this planet.",
        "Human activity detected.",
    ]

    SAA_COMPLETE = [
        "Surface scan complete. {body} fully mapped.",
        "{body} has been mapped. Bonus credits applied.",
        "DSS mapping complete on {body}.",
        "Probe mapping done. {body} charted.",
        "{body}, mapped top to bottom. Good work.",
    ]

    MEGASHIP_PP_MERITS = [
        "Megaship detected. PowerPlay merits available.",
        "Megaship on sensors. Scan for merits.",
        "Megaship signal confirmed. Worth scanning.",
        "Megaship in range. PowerPlay merits available.",
    ]

    NHSS_DETECTED = [
        "Non-human signal source detected. Threat level {threat}.",
        "Non-human signal source on sensors. Threat level {threat}.",
        "Caution. Non-human signal source. Threat level {threat}.",
    ]

    MEGASHIP_PP_UNDERMINING = [
        "Megaship detected. Scan for undermining merits.",
        "Megaship on sensors. Undermining merits available.",
        "Megaship signal. Undermining target — scan it.",
    ]

    MEGASHIP_PP_REINFORCEMENT = [
        "Megaship detected. Scan for reinforcement merits.",
        "Megaship on sensors. Reinforcement merits available.",
        "Megaship signal. Reinforce — scan the megaship.",
    ]

    MEGASHIP_PP_ACQUISITION = [
        "Megaship detected. Scan for acquisition merits.",
        "Megaship on sensors. Acquisition merits available.",
        "Megaship signal. Acquisition target — scan it.",
    ]

    CODEX_ENTRY = [
        "New codex entry. {name}.",
        "Discovery logged. {name}.",
        "Codex updated. {name} recorded.",
        "New entry. {name}.",
        "Something new for the logbook. {name}.",
    ]

    @staticmethod
    def fsd_announce() -> str:
        """Pre-jump base phrase (StartJump)."""
        return pick(ExplorationPhrases.FSD_JUMP)

    @staticmethod
    def in_system(system: str) -> str:
        """Startup location announcement (already in system)."""
        return pick(ExplorationPhrases.IN_SYSTEM, system=system)

    @staticmethod
    def arrived() -> str:
        return pick(ExplorationPhrases.ARRIVED)

    @staticmethod
    def security_state(security: str) -> str:
        """Format security string for speech.
        Handles localised ('High security') and bare token form ('High')."""
        s = security.strip()
        s_lower = s.lower()
        if s_lower in ("anarchy", "lawless"):
            return s.capitalize() + " system."
        if "security" in s_lower:
            return s + "."
        return s + " security."

    @staticmethod
    def valuable_bodies_summary(count: int) -> str:
        return pick(ExplorationPhrases.VALUABLE_BODIES_SUMMARY, count=count)

    @staticmethod
    def fss_complete(bodies: int) -> str:
        return pick(ExplorationPhrases.FSS_COMPLETE, bodies=bodies)

    @staticmethod
    def first_discovery(body: str) -> str:
        return pick(ExplorationPhrases.FIRST_DISCOVERY, body=body)

    @staticmethod
    def first_mapped(body: str) -> str:
        return pick(ExplorationPhrases.FIRST_MAPPED, body=body)

    @staticmethod
    def first_footfall(body: str) -> str:
        return pick(ExplorationPhrases.FIRST_FOOTFALL, body=body)

    @staticmethod
    def bio_signals(body: str, count: int) -> str:
        return pick(ExplorationPhrases.BIO_SIGNALS)

    @staticmethod
    def geo_signals(body: str, count: int) -> str:
        return pick(ExplorationPhrases.GEO_SIGNALS)

    @staticmethod
    def guardian_signals(body: str, count: int) -> str:
        pool = (ExplorationPhrases.GUARDIAN_SIGNALS_MULTIPLE
                if count > 1 else ExplorationPhrases.GUARDIAN_SIGNALS)
        return pick(pool, count=count)

    @staticmethod
    def guardian_signals_uncharted(body: str, count: int) -> str:
        pool = (ExplorationPhrases.GUARDIAN_SIGNALS_UNCHARTED_MULTIPLE
                if count > 1 else ExplorationPhrases.GUARDIAN_SIGNALS_UNCHARTED)
        return pick(pool, count=count)

    @staticmethod
    def thargoid_signals(body: str, count: int) -> str:
        pool = (ExplorationPhrases.THARGOID_SIGNALS_MULTIPLE
                if count > 1 else ExplorationPhrases.THARGOID_SIGNALS)
        return pick(pool, count=count)

    @staticmethod
    def human_signals(body: str, count: int) -> str:
        return pick(ExplorationPhrases.HUMAN_SIGNALS)

    @staticmethod
    def saa_complete(body: str) -> str:
        return pick(ExplorationPhrases.SAA_COMPLETE, body=body)

    @staticmethod
    def signals_summary(bio: int, geo: int, human: int) -> str:
        parts = []
        if bio > 0:
            parts.append(f"{bio} bio signal {'body' if bio == 1 else 'bodies'}")
        if geo > 0:
            parts.append(f"{geo} geo signal {'body' if geo == 1 else 'bodies'}")
        if human > 0:
            parts.append(f"{human} human signal {'body' if human == 1 else 'bodies'}")
        if not parts:
            return ""
        return "System survey: " + ", ".join(parts) + "."

    @staticmethod
    def megaship_pp_merits(activity: str = "") -> str:
        if activity == "undermining":
            return pick(ExplorationPhrases.MEGASHIP_PP_UNDERMINING)
        if activity == "reinforcement":
            return pick(ExplorationPhrases.MEGASHIP_PP_REINFORCEMENT)
        if activity == "acquisition":
            return pick(ExplorationPhrases.MEGASHIP_PP_ACQUISITION)
        return pick(ExplorationPhrases.MEGASHIP_PP_MERITS)

    @staticmethod
    def nhss_detected(threat: int) -> str:
        return pick(ExplorationPhrases.NHSS_DETECTED, threat=threat)

    @staticmethod
    def codex_entry(name: str) -> str:
        return pick(ExplorationPhrases.CODEX_ENTRY, name=name)
