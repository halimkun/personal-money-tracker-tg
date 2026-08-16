"""Test quick-add AI: parsing teks (client di-mock) + resolusi kategori/wallet."""

from decimal import Decimal

import pytest

from app.ai import quick_add as qa
from app.ai import client as ai_client
from tests.conftest import make_category, make_user, make_wallet


@pytest.fixture
def mock_complete(monkeypatch):
    """Ganti complete_json dengan callable yang bisa diatur per-test."""
    responses = {}

    async def fake_complete_json(session, messages, *, temperature=0.0):
        user_msg = messages[-1]["content"]
        if isinstance(user_msg, list):  # pesan gambar
            user_msg = user_msg[0]["text"]
        return responses.get("json", {"action": "unclear"})

    monkeypatch.setattr(ai_client, "complete_json", fake_complete_json)
    return responses


class TestParseText:
    async def test_happy_path(self, session, mock_complete):
        user = await make_user(session)
        await make_wallet(session, user.id, name="Cash")
        await make_category(session, None, name="Makan & Minum", type_="expense")
        mock_complete["json"] = {
            "action": "transaction", "type": "expense", "amount": 25000,
            "category_guess": "Makan & Minum", "wallet_guess": "Cash",
            "note": "beli kopi", "confidence": "high",
        }
        result = await qa.parse_text(session, user.id, "beli kopi 25rb")
        assert not result.is_unclear
        assert result.action == "transaction"
        assert result.type == "expense"
        assert result.amount == Decimal("25000.00")

    async def test_unclear_action(self, session, mock_complete):
        user = await make_user(session)
        mock_complete["json"] = {"action": "unclear", "confidence": "high"}
        result = await qa.parse_text(session, user.id, "halo apa kabar")
        assert result.is_unclear

    async def test_low_confidence_unclear(self, session, mock_complete):
        user = await make_user(session)
        mock_complete["json"] = {
            "action": "transaction", "type": "expense", "amount": 10000,
            "confidence": "low",
        }
        result = await qa.parse_text(session, user.id, "beli sesuatu")
        assert result.is_unclear  # PRD: confidence rendah → tidak memaksakan

    async def test_missing_amount_unclear(self, session, mock_complete):
        user = await make_user(session)
        mock_complete["json"] = {
            "action": "transaction", "type": "expense", "amount": None,
            "confidence": "high",
        }
        result = await qa.parse_text(session, user.id, "makan siang")
        assert result.is_unclear

    async def test_transfer(self, session, mock_complete):
        user = await make_user(session)
        await make_wallet(session, user.id, name="Cash")
        await make_wallet(session, user.id, name="GoPay", is_default=False)
        mock_complete["json"] = {
            "action": "transfer", "amount": 100000,
            "from_wallet_guess": "Cash", "to_wallet_guess": "GoPay",
            "confidence": "high",
        }
        result = await qa.parse_text(session, user.id, "transfer 100rb dari cash ke gopay")
        assert not result.is_unclear
        assert result.action == "transfer"
        assert result.type is None


class TestResolve:
    async def test_resolve_category_by_name(self, session):
        user = await make_user(session)
        cat = await make_category(session, None, name="Makan & Minum", type_="expense")
        resolved = await qa.resolve_category(session, user.id, "makan & minum", "expense")
        assert resolved.id == cat.id

    async def test_resolve_category_by_keyword(self, session):
        from app.db.models import Category

        user = await make_user(session)
        cat = Category(user_id=None, name="Ngopi", type="expense", icon="☕",
                       keywords=["kopi", "starbucks"])
        session.add(cat)
        await session.flush()
        resolved = await qa.resolve_category(session, user.id, "starbucks", "expense")
        assert resolved.id == cat.id

    async def test_resolve_category_fallback(self, session):
        user = await make_user(session)
        await make_category(session, None, name="Lainnya", type_="expense")
        resolved = await qa.resolve_category(session, user.id, None, "expense")
        assert resolved.name == "Lainnya"

    async def test_resolve_wallet_match_and_default(self, session):
        user = await make_user(session)
        w1 = await make_wallet(session, user.id, name="Cash")
        w2 = await make_wallet(session, user.id, name="BCA", is_default=False)
        assert (await qa.resolve_wallet(session, user.id, "bca")).id == w2.id
        assert (await qa.resolve_wallet(session, user.id, None)).id == w1.id  # default
        assert (await qa.resolve_wallet(session, user.id, "tidak ada")).id == w1.id
