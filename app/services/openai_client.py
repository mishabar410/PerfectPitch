"""Shared OpenAI client instance.

The client reads OPENAI_API_KEY from environment.
"""

from openai import OpenAI


client = OpenAI()


