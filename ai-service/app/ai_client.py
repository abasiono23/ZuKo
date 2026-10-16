"""Shared OpenAI client and a structured-output helper.

All model calls go through `structured_call`, which:
  * asks for JSON matching a Pydantic model (Responses API structured outputs),
  * returns None on any failure so callers can fall back to deterministic logic.
"""

import logging
import os
from functools import lru_cache
from typing import TypeVar

import openai
from pydantic import BaseModel

from app.config import get_settings

log = logging.getLogger("zuko.ai")

T = TypeVar("T", bound=BaseModel)


@lru_cache
def get_client() -> openai.OpenAI | None:
    settings = get_settings()
    if not settings.ai_enabled:
        return None
    if not os.getenv("OPENAI_API_KEY"):
        log.warning("No OPENAI_API_KEY set; using the rules engine")
        return None
    return openai.OpenAI(timeout=60.0, max_retries=2)


def structured_call(
    *,
    system: str,
    messages: list[dict],
    output_model: type[T],
    effort: str,
    max_tokens: int = 16000,
) -> T | None:
    client = get_client()
    if client is None:
        return None
    settings = get_settings()
    kwargs = {"reasoning": {"effort": effort}} if settings.ai_model.startswith(("gpt-5", "gpt-6", "o")) else {}
    try:
        response = client.responses.parse(
            model=settings.ai_model,
            instructions=system,
            input=messages,
            text_format=output_model,
            max_output_tokens=max_tokens,
            prompt_cache_key=output_model.__name__,
            **kwargs,
        )
    except openai.AuthenticationError as exc:
        log.warning("OpenAI auth failed, using rules engine: %s", exc)
        return None
    except openai.RateLimitError as exc:
        log.warning("OpenAI rate limited, using rules engine: %s", exc)
        return None
    except openai.APIStatusError as exc:
        log.error("OpenAI API error %s: %s", exc.status_code, exc)
        return None
    except openai.APIConnectionError as exc:
        log.warning("OpenAI unreachable, using rules engine: %s", exc)
        return None
    except Exception as exc:  # schema validation of the parsed output, etc.
        log.error("OpenAI call failed: %s", exc)
        return None

    if response.status != "completed":
        log.warning("OpenAI response %s (%s); discarding", response.status, response.incomplete_details)
        return None
    if response.output_parsed is None:
        log.warning("OpenAI returned no parsed output (likely a refusal)")
        return None
    return response.output_parsed
