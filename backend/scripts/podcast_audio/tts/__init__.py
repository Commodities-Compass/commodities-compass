"""Speech synthesis behind one interface, so the engine stays swappable.

Same shape as ``AlertSender``/``ALERT_CHANNEL`` in ``intraday_monitor``: the
pipeline never names a vendor, and ``TTS_PROVIDER`` picks one.
"""

from scripts.podcast_audio.tts.base import (
    SpeechSynthesizer,
    SynthesisError,
    get_synthesizer,
)

__all__ = ["SpeechSynthesizer", "SynthesisError", "get_synthesizer"]
