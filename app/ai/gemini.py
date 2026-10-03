import asyncio
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

T = TypeVar("T", bound=BaseModel)


log = logging.getLogger("uvicorn.error")


class AiUnavailable(Exception):
    """Model call failed, timed out, or returned something that does not match the schema."""


async def generate_json(system: str, prompt: str, schema: type[T]) -> T:
    """Calls Gemini and validates the JSON against `schema`. The API key never leaves the backend."""
    if not settings.gemini_api_key:
        log.warning("gemini: GEMINI_API_KEY is empty (is it set in backend/.env and was uvicorn restarted?)")
        raise AiUnavailable("not configured")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.6,
                    max_output_tokens=getattr(schema, "max_output_tokens", 2048),
                ),
            ),
            timeout=max(settings.gemini_timeout_s, getattr(schema, "timeout_s", 0)),
        )
        return schema.model_validate_json(resp.text or "")
    except (asyncio.TimeoutError, ValidationError, ValueError) as exc:
        log.warning("gemini %s: %s", type(exc).__name__, str(exc)[:400])
        raise AiUnavailable(type(exc).__name__) from exc
    except Exception as exc:  # network/quota/API errors
        log.warning("gemini %s: %s", type(exc).__name__, str(exc).replace(settings.gemini_api_key, "***")[:600])
        raise AiUnavailable(type(exc).__name__) from exc
