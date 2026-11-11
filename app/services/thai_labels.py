"""Thai names and hints for the central categories (STORY-019).

Display only: the English name stays the group standard and is what codes,
Name Prefixes, product names and exports use. These labels only help
people pick the right category.

Keys are the group code ("900") or group-sub ("900-02"), the same keys as
app/data/taxonomy_th.json.
"""

import unicodedata

from app.services.snapshots import fix_thai

NAME_TH_MAX = 100
HINT_TH_MAX = 300


class LabelError(ValueError):
    """A Thai label that must not be saved; the message is Thai, for people."""


def clean_label(text: str | None, max_len: int, what: str) -> str | None:
    """NFC (never NFKC) + recomposed SARA AM, whitespace collapsed.

    Empty means "no Thai label" (None). Too long raises LabelError.
    """
    text = fix_thai(unicodedata.normalize("NFC", text or ""))
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) > max_len:
        raise LabelError(f"{what}ยาวเกิน {max_len} ตัวอักษร (ตอนนี้ {len(text)})")
    return text
