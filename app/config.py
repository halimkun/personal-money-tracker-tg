"""Konfigurasi aplikasi — dibaca dari environment / .env."""

from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Bot
    bot_token: str = ""
    bot_mode: str = "polling"  # polling | webhook
    admin_ids: str = ""  # dipisah koma, mis. "123,456"

    # Database
    database_url: str = "sqlite+aiosqlite:///bot.db"

    # FSM storage (opsional — fallback MemoryStorage untuk dev)
    redis_url: str = ""

    # Webhook (hanya dipakai kalau bot_mode=webhook)
    webhook_host: str = ""
    webhook_path: str = "/webhook/telegram"
    webhook_secret_token: str = ""
    webapp_host: str = "0.0.0.0"
    webapp_port: int = 8080

    # Keamanan
    encryption_key: str = ""

    # Default global (bisa diubah admin via /admin)
    timezone: str = "Asia/Jakarta"
    free_transaction_limit: int = 200
    ai_daily_limit: int = 30
    quick_add_draft_ttl_minutes: int = 15
    callback_ref_ttl_minutes: int = 15

    @property
    def admin_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(",", " ").split() if x.strip().isdigit()}

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


settings = Settings()
