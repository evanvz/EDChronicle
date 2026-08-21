"""Engineering wishlist TTS phrase module."""
from edc.audio.tts_phrases import pick


class EngineeringPhrases:

    MATERIAL_NEARBY = [
        "{material} available nearby. Wishlist item.",
        "Wishlist alert. {material} can be found here.",
        "{material} needed for your build — reachable from here.",
        "You're near a source of {material}, on your wishlist.",
        "{material}, Commander — you're right next to some.",
        "Worth a detour — {material} is close by, and you need it.",
        "That build of yours needs {material}. There's some nearby.",
    ]

    @staticmethod
    def material_nearby(material: str) -> str:
        return pick(EngineeringPhrases.MATERIAL_NEARBY, material=material)
