"""Size / dimension normalization.

Users write the same size a dozen ways (4 นิ้ว, 4inch, 4", 4 IN / cm, CM, cm. /
10 X 20, 10*20, 10 x 20). This module rewrites them into one canonical form.

Canonical choices are taken from what actually dominates the real CBD master
(22.5k names), not invented:
  - inch  -> "        (2" appears 495x, far ahead of 'inch'/'นิ้ว')
  - metric -> lowercase mm / cm / m   ('mm' 1946x vs 'MM'/'มม.')
  - mass/volume -> kg, g, ml, L
  - dimensions -> compact 'x'  (10x20 appears 1710x vs 171 spaced, 347 'X')
  - number and unit are joined: '4 mm' -> '4mm'

Dimension order is only rearranged when the user LABELS the dimensions
(กว้าง/ยาว/สูง). Bare numbers are never reordered — 10x20 and 20x10 can mean
different things and guessing would corrupt the spec.
"""

import re

# Longest patterns first so 'มิลลิเมตร' wins over 'ม'.
_UNIT_MAP: list[tuple[str, str]] = [
    (r"มิลลิเมตร|มิลลิลิตร?เมตร|มม\.?|มิล\b", "mm"),
    (r"เซนติเมตร|เซ็นติเมตร|ซม\.?", "cm"),
    (r"กิโลกรัม|กิโล\b|กก\.?", "kg"),
    (r"มิลลิลิตร|มล\.?", "ml"),
    (r"ลิตร", "L"),
    (r"กรัม", "g"),
    (r"เมตร|ม\.", "m"),
    (r"นิ้ว|inches|inch|\bin\b", '"'),
    (r"\bmm\b|\bMM\b|\bMm\b", "mm"),
    (r"\bcm\b|\bCM\b|\bCm\b", "cm"),
    (r"\bkg\b|\bKG\b|\bKg\b", "kg"),
    (r"\bml\b|\bML\b|\bMl\b", "ml"),
    (r"\bltr\b|\blitre\b|\bliter\b", "L"),
]

# Dimension labels -> canonical slot order: กว้าง(W) x ยาว(L) x สูง(H)
_DIM_LABELS: list[tuple[str, int]] = [
    (r"กว้าง|width|\bW\b", 0),
    (r"ยาว|length|\bL\b(?!\s*$)", 1),
    (r"สูง|ลึก|height|depth|\bH\b|\bD\b", 2),
]


def _canonical_units(text: str) -> str:
    # 'cm.' / '25mm.' -> drop the abbreviation dot before mapping.
    # No leading \b: there is no word boundary between '5' and 'c' in '25cm'.
    text = re.sub(r"(mm|cm|kg|ml|in)\.(?!\w)", r"\1", text, flags=re.IGNORECASE)
    for pattern, canonical in _UNIT_MAP:
        text = re.sub(pattern, canonical, text, flags=re.IGNORECASE)
    return text


def _join_number_unit(text: str) -> str:
    # '4 mm' -> '4mm' ; '4 "' -> '4"'
    return re.sub(r'(\d)\s+(mm|cm|kg|ml|"|[LgmM]\b)', r"\1\2", text)


def _normalize_separators(text: str) -> str:
    # any of x X × * (with or without spaces) between numbers -> compact 'x'
    return re.sub(
        r'(\d(?:\.\d+)?(?:mm|cm|kg|ml|[LgmM]|")?)\s*[xX×*]\s*(?=\d)', r"\1x", text
    )


def _reorder_labeled(text: str) -> str | None:
    """If the user labeled dimensions, emit them in W x L x H order.
    Returns None when there are no labels (caller keeps the original order)."""
    found: dict[int, str] = {}
    for pattern, slot in _DIM_LABELS:
        m = re.search(
            rf'(?:{pattern})\s*[:=]?\s*(\d+(?:\.\d+)?\s*(?:mm|cm|kg|ml|[Lgm]|")?)',
            text,
            flags=re.IGNORECASE,
        )
        if m and slot not in found:
            found[slot] = m.group(1).replace(" ", "")
    if len(found) < 2:
        return None
    return "x".join(found[slot] for slot in sorted(found))


def normalize_size(raw: str | None) -> str:
    """Return the canonical rendering of a size string. Safe on empty input."""
    if not raw or not raw.strip():
        return ""
    text = " ".join(raw.split())
    text = _canonical_units(text)

    reordered = _reorder_labeled(text)
    if reordered:
        return reordered

    # join number+unit first ('10 mm' -> '10mm') so the separator pass sees
    # complete tokens on both sides of the x
    text = _join_number_unit(text)
    text = _normalize_separators(text)
    return " ".join(text.split())
