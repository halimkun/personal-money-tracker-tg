"""Akses global_settings (key-value) dengan tipe & default — PRD §4.

AI api_key disimpan terenkripsi (Fernet) — lihat app.utils.crypto.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.repositories.admin_logs import AdminLogRepo
from app.repositories.global_settings import GlobalSettingsRepo
from app.utils.crypto import decrypt, encrypt

DEFAULTS: dict[str, str] = {
    "payment_required": "false",
    "free_transaction_limit": str(app_settings.free_transaction_limit),
    "ai_insight_enabled_global": "true",
    "ai_api_key": "",  # terenkripsi
    "ai_base_url": "https://api.openai.com/v1",
    "ai_model": "gpt-4o-mini",
    "ai_daily_limit": str(app_settings.ai_daily_limit),
    "ai_price_per_1m": "",  # opsional, untuk estimasi biaya di /stats
    "premium_price": "50000",
    "premium_duration_days": "365",
    "payment_instructions": "Transfer ke rekening admin, lalu kirim bukti transfer ke bot ini.",
}


class SettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = GlobalSettingsRepo(session)

    async def get(self, key: str) -> str:
        value = await self.repo.get(key)
        return value if value is not None else DEFAULTS.get(key, "")

    async def get_bool(self, key: str) -> bool:
        return (await self.get(key)).strip().lower() in ("1", "true", "yes", "on")

    async def get_int(self, key: str) -> int:
        try:
            return int(await self.get(key))
        except ValueError:
            return int(DEFAULTS.get(key, 0) or 0)

    async def get_decimal(self, key: str) -> Decimal:
        try:
            return Decimal(await self.get(key))
        except Exception:
            return Decimal(DEFAULTS.get(key, "0") or 0)

    async def set(self, key: str, value: str, admin_id: int | None = None) -> None:
        await self.repo.set(key, value)
        if admin_id is not None:
            await AdminLogRepo(self.repo.s).add(admin_id, f"set_{key}", {"value": value})

    # -- Typed helpers -------------------------------------------------

    async def payment_required(self) -> bool:
        return await self.get_bool("payment_required")

    async def free_limit(self) -> int:
        return await self.get_int("free_transaction_limit")

    async def insight_enabled_global(self) -> bool:
        return await self.get_bool("ai_insight_enabled_global")

    async def ai_daily_limit(self) -> int:
        return await self.get_int("ai_daily_limit")

    async def ai_config(self) -> dict:
        """Konfigurasi AI: api_key (terdekripsi), base_url, model."""
        raw_key = await self.get("ai_api_key")
        try:
            api_key = decrypt(raw_key) if raw_key else ""
        except Exception:
            api_key = ""
        return {
            "api_key": api_key,
            "base_url": await self.get("ai_base_url"),
            "model": await self.get("ai_model"),
        }

    async def set_ai_api_key(self, value: str, admin_id: int) -> None:
        await self.set("ai_api_key", encrypt(value) if value else "", admin_id)

    async def premium_price(self) -> Decimal:
        return await self.get_decimal("premium_price")

    async def premium_duration_days(self) -> int:
        return await self.get_int("premium_duration_days")

    async def payment_instructions(self) -> str:
        return await self.get("payment_instructions")

    async def ai_price_per_1m(self) -> Decimal | None:
        raw = await self.get("ai_price_per_1m")
        try:
            return Decimal(raw) if raw else None
        except Exception:
            return None

    async def ai_month_counters(self, month_label: str) -> dict[str, int]:
        calls = int(await self.repo.get(f"ai_calls_{month_label}") or 0)
        pt = int(await self.repo.get(f"ai_prompt_tokens_{month_label}") or 0)
        ct = int(await self.repo.get(f"ai_completion_tokens_{month_label}") or 0)
        return {"calls": calls, "prompt_tokens": pt, "completion_tokens": ct}
