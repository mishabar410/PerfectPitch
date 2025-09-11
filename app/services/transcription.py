"""Speech-to-text utilities using OpenAI Whisper.

transcribe_audio() returns plain text using whisper-1 with response_format="text".
"""

from pathlib import Path
from typing import Optional

from .openai_client import client
import logging


def transcribe_audio(audio_path: Path, lang_hint: Optional[str] = None) -> str:
    """Transcribe audio/video file to plain text using Whisper.

    Raises FileNotFoundError if audio_path does not exist.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    with open(audio_path, "rb") as f:
        tr = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=lang_hint or None,
            response_format="text",
        )
    logging.getLogger(__name__).info("whisper_transcribed", extra={"path": str(audio_path), "lang_hint": lang_hint})
    return tr


