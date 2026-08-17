"""Tes AI quick-add dari terminal — cek apakah AI aktif & lihat hasil parsing.

Tanpa perlu klik-klik di Telegram: baca konfigurasi AI langsung dari DB,
kirim pesan uji, tampilkan respons mentah + hasil parsing + latensi.

Pemakaian:
  uv run python scripts/ai_check.py                         # status + 1 health check
  uv run python scripts/ai_check.py "KFC 2 60000"           # tes pesan tertentu
  uv run python scripts/ai_check.py "pesan 1" "pesan 2"     # tes beberapa pesan
  uv run python scripts/ai_check.py --loop                  # tes interaktif berulang

Set konfigurasi AI (simpan permanen ke DB, sama seperti /admin → Konfigurasi AI):
  uv run python scripts/ai_check.py --set-base-url https://api.example.com/v1
  uv run python scripts/ai_check.py --set-model deepseek-v4-flash
  uv run python scripts/ai_check.py --set-api-key sk-xxxx
  (flag boleh digabung, dan bisa langsung diikuti pesan uji)

Catatan: panggilan dihitung sebagai pemakaian AI (masuk statistik /stats),
dan tetap tunduk rate limit provider. API key lewat CLI bisa masuk shell
history — pertimbangkan spasi di depan command (history ignore) bila perlu.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.ai import client, quick_add as qa_ai
from app.ai.client import AIError
from app.config import settings
from app.db.models import User
from app.db.session import session_factory
from app.repositories.users import UserRepo
from app.services.settings import SettingsService

DEFAULT_TEST = "beli kopi 25rb"


def _mask_key(key: str) -> str:
    return (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("(ada)" if key else "(kosong)")


async def _resolve_user(session) -> User | None:
    """User untuk context (kategori & wallet): admin pertama, atau user pertama."""
    for tg_id in settings.admin_set:
        u = await UserRepo(session).get_by_telegram_id(tg_id)
        if u:
            return u
    res = await session.execute(select(User).order_by(User.id).limit(1))
    return res.scalars().first()


async def show_status(session) -> None:
    cfg = await SettingsService(session).ai_config()
    print("─ Status AI ─")
    print(f"  api_key : {_mask_key(cfg['api_key'])}")
    print(f"  base_url: {cfg['base_url']}")
    print(f"  model   : {cfg['model']}")
    print(f"  tz      : {settings.tz}")


async def test_message(session, user_id: int | None, text: str) -> None:
    print(f"\n─ Pesan: {text!r} ─")
    context = await qa_ai.build_context(session, user_id) if user_id else \
        "Daftar kategori: (tidak ada)\nDaftar wallet: (tidak ada)"
    messages = [
        {"role": "system", "content": qa_ai._system_prompt()},
        {"role": "user", "content": f"{context}\n\nPesan user: {text}"},
    ]
    t0 = time.monotonic()
    try:
        data = await client.complete_json(session, messages)
    except AIError as e:
        msg = str(e)
        if "429" in msg:
            print("⚠️  Rate limit provider (HTTP 429) — AI AKTIF tapi sedang dibatasi.")
            print("   Tunggu beberapa menit, atau pakai provider/model dengan kuota lebih besar.")
        elif "401" in msg or "auth" in msg.lower():
            print("🔑 API key DITOLAK provider (HTTP 401) — key tidak valid/kedaluwarsa/")
            print("   belum terdaftar. Ganti di /admin → 🤖 Konfigurasi AI.")
        else:
            print(f"❌ {msg}")
        return
    latency = time.monotonic() - t0
    print(f"  latensi: {latency:.1f}s")
    print(f"  respons mentah:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
    result = await qa_ai._parse_result(data)
    print(f"  hasil parse: action={result.action} type={result.type} "
          f"amount={result.amount} date={result.date_iso} "
          f"confidence={result.confidence} unclear={result.is_unclear}")


async def apply_config(session, base_url: str | None, model: str | None,
                       api_key: str | None) -> None:
    """Simpan konfigurasi AI ke DB (setara /admin → 🤖 Konfigurasi AI)."""
    svc = SettingsService(session)
    admin_id = next(iter(settings.admin_set), None)
    if base_url is not None:
        await svc.set("ai_base_url", base_url, admin_id)
        print(f"✅ base_url disimpan: {base_url}")
    if model is not None:
        await svc.set("ai_model", model, admin_id)
        print(f"✅ model disimpan: {model}")
    if api_key is not None:
        value = "" if api_key.strip() == "-" else api_key.strip()
        await svc.set_ai_api_key(value, admin_id)
        print(f"✅ api_key disimpan (terenkripsi): {_mask_key(value)}")
    await session.commit()
    client.clear_cache()


async def run(messages: list[str], loop: bool, *, set_base_url: str | None = None,
              set_model: str | None = None, set_api_key: str | None = None) -> None:
    async with session_factory() as session:
        await apply_config(session, set_base_url, set_model, set_api_key)
        await show_status(session)
        user = await _resolve_user(session)
        print(f"  context user: {user.full_name if user else '(tidak ada — tanpa kategori/wallet)'}")
        if loop:
            while True:
                text = (await asyncio.to_thread(input, "\nPesan uji (kosong = keluar): ")).strip()
                if not text:
                    break
                await test_message(session, user.id if user else None, text)
        else:
            for text in messages or [DEFAULT_TEST]:
                await test_message(session, user.id if user else None, text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tes AI quick-add dari terminal.")
    parser.add_argument("messages", nargs="*", help="pesan uji (default: beli kopi 25rb)")
    parser.add_argument("--loop", action="store_true", help="tes interaktif berulang")
    parser.add_argument("--set-base-url", metavar="URL", help="simpan base_url ke DB")
    parser.add_argument("--set-model", metavar="MODEL", help="simpan model ke DB")
    parser.add_argument("--set-api-key", metavar="KEY",
                        help="simpan api_key ke DB (terenkripsi; '-' untuk kosongkan)")
    args = parser.parse_args()
    asyncio.run(run(args.messages, args.loop, set_base_url=args.set_base_url,
                    set_model=args.set_model, set_api_key=args.set_api_key))


if __name__ == "__main__":
    main()
