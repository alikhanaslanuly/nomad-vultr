import json
import re
import time

import httpx

from openai import AsyncOpenAI

from app.config import settings

_client = None


def get_client():
    global _client
    if not settings.INFERENCE_API_KEY:
        raise RuntimeError("Inference is not configured")
    if _client is None:
        _client = AsyncOpenAI(
            base_url=settings.INFERENCE_BASE_URL,
            api_key=settings.INFERENCE_API_KEY,
            timeout=20,
            max_retries=0,
        )
    return _client


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


async def chat_json(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1500,
    retries: int = 1,
) -> tuple[dict[str, object], int, int]:

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        resp = await get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        tokens_in = resp.usage.prompt_tokens if resp.usage else 0
        tokens_out = resp.usage.completion_tokens if resp.usage else 0
        try:
            return json.loads(_strip_fences(raw)), tokens_in, tokens_out
        except json.JSONDecodeError as e:
            last_err = e
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your reply was not valid JSON: {e}. Reply with a single JSON object only.",
                }
            )
    raise RuntimeError(f"LLM did not return valid JSON: {last_err}")


async def chat_text(
    model: str, system: str, user: str, max_tokens: int = 800
) -> tuple[str, int, int]:
    resp = await get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return (
        resp.choices[0].message.content or "",
        resp.usage.prompt_tokens if resp.usage else 0,
        resp.usage.completion_tokens if resp.usage else 0,
    )


async def list_models() -> list[str]:
    page = await get_client().models.list()
    return [m.id for m in page.data]


_health_at = 0.0
_health_ok = False


async def inference_health() -> bool:
    global _health_at, _health_ok
    if not settings.INFERENCE_API_KEY:
        return False
    if _health_at and time.monotonic() - _health_at < 60:
        return _health_ok
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(
                f"{settings.INFERENCE_BASE_URL.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.INFERENCE_API_KEY}"},
            )
            response.raise_for_status()
            models = {item["id"] for item in response.json()["data"]}
            _health_ok = {
                settings.INFERENCE_MODEL_PLANNER,
                settings.INFERENCE_MODEL_EXPLAINER,
            } <= models
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        _health_ok = False
    _health_at = time.monotonic()
    return _health_ok
