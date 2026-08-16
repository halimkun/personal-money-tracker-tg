"""Registry draft quick-add (kartu konfirmasi) untuk auto-expire (PRD §5.1b poin 6).

Hanya penunjuk ringan ke pesan kartu — payload asli ada di FSM data. Registry dipakai
job scheduler untuk meng-clear state & menandai kartu kadaluarsa.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DraftEntry:
    user_id: int
    chat_id: int
    message_id: int
    expires_at: datetime


class DraftRegistry:
    def __init__(self) -> None:
        self._drafts: dict[int, DraftEntry] = {}

    def register(self, entry: DraftEntry) -> None:
        self._drafts[entry.user_id] = entry

    def unregister(self, user_id: int) -> None:
        self._drafts.pop(user_id, None)

    def snapshot(self) -> list[DraftEntry]:
        return list(self._drafts.values())


draft_registry = DraftRegistry()
