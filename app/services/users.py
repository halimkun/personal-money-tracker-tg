"""Layanan manajemen user: registrasi, premium, status akun."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.money import format_rupiah
from app.repositories.users import UserRepo
from app.repositories.wallets import WalletRepo
from app.services.settings import SettingsService
from app.services.wallets import WalletService
from app.utils.format import fmt_datetime


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def register(self, tg_id: int, username: str | None, full_name: str | None) -> tuple[User, bool]:
        """Get-or-create user. Return (user, is_new)."""
        repo = UserRepo(self.s)
        user = await repo.get_by_telegram_id(tg_id)
        if user:
            user.username = username
            user.full_name = full_name
            return user, False
        return await repo.create(tg_id, username, full_name), True

    async def grant_premium(self, user: User, until: datetime | None) -> None:
        """Grant premium. until=None berarti lifetime (grant manual admin)."""
        user.is_premium = True
        user.premium_until = until

    async def build_status_text(self, user: User) -> str:
        """Teks /status: kuota gratis, status premium, ringkasan saldo semua wallet."""
        lines = [f"👤 <b>{user.full_name or '—'}</b>"]
        if user.username:
            lines[0] += f" (@{user.username})"

        settings_svc = SettingsService(self.s)
        payment_required = await settings_svc.payment_required()
        if user.is_premium:
            if user.premium_until:
                lines.append(f"💎 Premium ✅ (sampai {fmt_datetime(user.premium_until)})")
            else:
                lines.append("💎 Premium ✅ (lifetime)")
        elif payment_required:
            free = user.free_transaction_count
            limit = await settings_svc.free_limit()
            lines.append(f"🆓 Kuota gratis: {free}/{limit} bulan ini")
            lines.append("💳 Status: Gratis — ketik /upgrade untuk premium")
        else:
            lines.append("🆓 Semua fitur gratis (monetisasi belum aktif)")

        balances = await WalletService(self.s).list_with_balances(user.id)
        if balances:
            lines.append("")
            lines.append("👛 <b>Saldo wallet:</b>")
            for wallet, balance in balances:
                star = " ⭐" if wallet.is_default else ""
                icon = {"cash": "💵", "bank": "🏦", "ewallet": "📱"}.get(wallet.type, "💼")
                lines.append(f"{icon} {wallet.name}{star}: <b>{format_rupiah(balance)}</b>")
        else:
            lines.append("👛 Belum ada wallet — buat lewat /wallet")
        return "\n".join(lines)

    async def toggle_insight(self, user: User) -> bool:
        """On/off insight AI bulanan per user. Return status baru."""
        user.ai_insight_enabled = not user.ai_insight_enabled
        return user.ai_insight_enabled

    async def monthly_reset(self) -> None:
        await UserRepo(self.s).reset_free_counters()

    async def expire_premiums(self) -> int:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return await UserRepo(self.s).expire_premiums(now)
