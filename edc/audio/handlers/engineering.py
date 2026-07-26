"""Engineering wishlist TTS phrase module."""
from edc.audio.tts_phrases import pick


class EngineeringPhrases:

    MATERIAL_NEARBY = [
        "{material} available nearby. Wishlist item.",
        "Wishlist alert. {material} can be found here.",
        "{material} needed for your build — reachable from here.",
        "You're near a source of {material}, on your wishlist.",
    ]

    @staticmethod
    def material_nearby(material: str) -> str:
        return pick(EngineeringPhrases.MATERIAL_NEARBY, material=material)
