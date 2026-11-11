"""Thai names and hints for the central categories (STORY-019).

Display only: the English name stays the group standard and is what codes,
Name Prefixes, product names and exports use. These labels only help
people pick the right category.

Keys are the group code ("900") or group-sub ("900-02"), the same keys as
app/data/taxonomy_th.json.
"""

import json
import unicodedata
from pathlib import Path

from app.services.snapshots import fix_thai

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LABEL_FILE = "app/data/taxonomy_th.json"

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


def parse_label_file(
    raw: dict, taxonomy: list[dict],
) -> dict[str, tuple[str | None, str | None]]:
    """Check taxonomy_th.json against the taxonomy; raises LabelError.

    Every key must be a group ("900") or group-sub ("900-02") of the
    taxonomy; values are {"name_th": ..., "hint_th": ...}, both optional.
    """
    keys = {r["group"] for r in taxonomy} | {f"{r['group']}-{r['sub']}" for r in taxonomy}
    out: dict[str, tuple[str | None, str | None]] = {}
    for key, value in raw.items():
        if key not in keys:
            raise LabelError(f"{LABEL_FILE}: ไม่มีหมวด '{key}' ใน taxonomy.json")
        if not isinstance(value, dict):
            raise LabelError(f"{LABEL_FILE}: '{key}' ต้องเป็น {{\"name_th\": ..., \"hint_th\": ...}}")
        try:
            out[key] = (
                clean_label(value.get("name_th"), NAME_TH_MAX, f"ชื่อไทยของ {key} "),
                clean_label(value.get("hint_th"), HINT_TH_MAX, f"ตัวอย่างของ {key} "),
            )
        except LabelError as e:
            raise LabelError(f"{LABEL_FILE}: {e}") from e
    return out


def file_labels() -> dict[str, tuple[str | None, str | None]]:
    """The labels in taxonomy_th.json, checked; raises LabelError."""
    def load(name: str):
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))

    return parse_label_file(load("taxonomy_th.json"), load("taxonomy.json"))
