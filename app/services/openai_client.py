"""OpenAI-compatible clients.

- chat_client: points to OpenRouter (uses OPENROUTER_API_KEY)
- audio_client: points to OpenAI for Whisper (uses OPENAI_API_KEY)
"""

import os
from openai import OpenAI


def _build_chat_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY") or ""
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    # Optional but recommended headers for OpenRouter analytics
    default_headers = {}
    referer = os.getenv("OPENROUTER_HTTP_REFERER")
    if referer:
        default_headers["HTTP-Referer"] = referer
    title = os.getenv("OPENROUTER_X_TITLE")
    if title:
        default_headers["X-Title"] = title
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers=default_headers or None,
    )


def _build_audio_client() -> OpenAI:
    # Use native OpenAI for Whisper unless overridden
    api_key = os.getenv("OPENAI_API_KEY") or ""
    # If not set, SDK defaults to api.openai.com
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(base_url=base_url, api_key=api_key)
    return OpenAI(api_key=api_key)


# Public clients
chat_client: OpenAI = _build_chat_client()
audio_client: OpenAI = _build_audio_client()

# Backward compatibility: many modules import `client` for chat
client: OpenAI = chat_client
