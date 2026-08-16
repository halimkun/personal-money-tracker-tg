"""Klien AI (OpenAI-compatible) — konfigurasi dibaca dari global_settings (PRD §2 & §5.2).

- base_url bisa diarahkan ke provider lain (OpenRouter, Groq, self-hosted, dst)
- api_key diambil dari DB (terenkripsi) — bisa diganti runtime tanpa redeploy
- penggunaan (calls + token) dicatat untuk pemantauan biaya di /stats
"""

import json
import logging
import re
from datetime import date

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings import SettingsService
from app.utils.format import today_local

log = logging.getLogger(__name__)

_client_cache: dict[tuple[str, str], AsyncOpenAI] = {}


class AIError(Exception):
    """Kesalahan AI yang layak ditampilkan ke user."""


def clear_cache() -> None:
    """Dipanggil saat admin mengubah setting AI (key/url)."""
    _client_cache.clear()


async def get_client(session: AsyncSession) -> tuple[AsyncOpenAI, str]:
    """Return (client, model) dari konfigurasi global_settings."""
    cfg = await SettingsService(session).ai_config()
    if not cfg["api_key"]:
        raise AIError("AI belum dikonfigurasi — admin bisa set API key lewat /setai.")
    key = (cfg["api_key"], cfg["base_url"])
    client = _client_cache.get(key)
    if client is None:
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=60)
        _client_cache[key] = client
    return client, cfg["model"]


async def track_usage(session: AsyncSession, usage) -> None:
    """Catat pemakaian AI bulan ini (pemantauan biaya, PRD §5.1b)."""
    from app.repositories.global_settings import GlobalSettingsRepo

    month = today_local().strftime("%Y-%m")
    repo = GlobalSettingsRepo(session)
    await repo.incr_int(f"ai_calls_{month}", 1)
    if usage:
        await repo.incr_int(f"ai_prompt_tokens_{month}", usage.prompt_tokens or 0)
        await repo.incr_int(f"ai_completion_tokens_{month}", usage.completion_tokens or 0)


async def complete_text(session: AsyncSession, messages: list[dict], *, temperature: float = 0.3) -> str:
    client, model = await get_client(session)
    try:
        resp = await client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
        )
    except Exception as e:
        raise AIError(f"AI request gagal: {e}") from e
    await track_usage(session, resp.usage)
    return (resp.choices[0].message.content or "").strip()


async def complete_json(session: AsyncSession, messages: list[dict], *, temperature: float = 0.0) -> dict:
    client, model = await get_client(session)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise AIError(f"AI request gagal: {e}") from e
    await track_usage(session, resp.usage)
    return _extract_json(resp.choices[0].message.content or "")


def _extract_json(content: str) -> dict:
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise AIError("Respons AI bukan JSON yang valid.")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise AIError("Respons AI bukan JSON yang valid.") from e
    if not isinstance(data, dict):
        raise AIError("Respons AI bukan objek JSON.")
    return data
