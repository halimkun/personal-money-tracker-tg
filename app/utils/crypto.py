"""Enkripsi simetris untuk secret di DB (mis. AI api_key) — PRD §2.

Kalau ENCRYPTION_KEY tidak diset, fallback plaintext dengan prefix "plain:"
(hanya untuk dev; production wajib set ENCRYPTION_KEY).
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_fernet: Fernet | None = None
_fernet_tried = False


def _get_fernet() -> Fernet | None:
    global _fernet, _fernet_tried
    if _fernet_tried:
        return _fernet
    _fernet_tried = True
    if settings.encryption_key:
        try:
            _fernet = Fernet(settings.encryption_key.encode())
        except Exception:
            _fernet = None
    return _fernet


def encrypt(text: str) -> str:
    f = _get_fernet()
    if f is None:
        return "plain:" + text
    return "enc:" + f.encrypt(text.encode()).decode()


def decrypt(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("plain:"):
        return stored[6:]
    if stored.startswith("enc:"):
        f = _get_fernet()
        if f is None:
            raise InvalidToken("ENCRYPTION_KEY tidak diset / tidak cocok")
        return f.decrypt(stored[4:].encode()).decode()
    return stored
