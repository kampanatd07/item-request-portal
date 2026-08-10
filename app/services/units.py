"""Size / dimension normalization.

Users write the same size a dozen ways (4 นิ้ว, 4inch, 4", 4 IN / cm, CM, cm. /
10 X 20, 10*20, 10 x 20). This module rewrites them into one canonical form.

Canonical choices are taken from what actually dominates the real CBD master
(22.5k names), not invented:
  - inch  -> "        (2" appears 495x, far ahead of 'inch'/'นิ้ว')
  - metric -> lowercase mm / cm / m   ('mm' 1946x vs 'MM'/'มม.')
  - mass/volume -> kg, g, ml, L
  - dimensions -> compact 'x'  (10x20 appears 1710x vs 171 spaced, 347 'X')
  - number and unit separated by one space: '20 L' (group naming rule 4);
    inch keeps the tight symbol form '4"'

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
    # no \b: there is no word boundary between a digit and a letter ('208LT')
    (r"(?<![A-Za-z])(?:ltr|litre|liter|lt)(?![A-Za-z])", "L"),
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


def _dedupe_chain_unit(text: str) -> str:
    """'10mmx20mm' -> '10x20mm'. A dimension chain states its unit once, at the
    end — matching the standard's own example 'M12x1.75x40 mm'."""
    for unit in ("mm", "cm", "kg", "ml", "L"):
        pattern = rf"(?<=\d){unit}(?=x\d)"
        if re.search(rf"{unit}(?=x\d)", text) and text.rstrip().endswith(unit):
            text = re.sub(pattern, "", text)
    return text


def _space_number_unit(text: str) -> str:
    """Group naming rule 4: one space between number and unit ('20 L', not '20L').
    Inch keeps the tight form ('4"') — it is a symbol, not a unit word."""
    text = re.sub(r'(\d)\s*"', r'\1"', text)  # 4 " -> 4"
    text = re.sub(r"(\d)(mm|cm|kg|ml|[LgmM])(?![A-Za-z])", r"\1 \2", text)
    return text


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

    # compact first so the separator pass sees complete tokens on both sides
    # of the x, then apply the mandated spacing
    text = re.sub(r'(\d)\s+(mm|cm|kg|ml|"|[LgmM])(?![A-Za-z])', r"\1\2", text)
    text = _normalize_separators(text)
    text = _dedupe_chain_unit(text)
    text = _space_number_unit(text)
    # trailing abbreviation dot left by inputs like '208LT.' / '20 ลิตร.'
    text = re.sub(r'(?<=[A-Za-z"])\.(?!\w)', "", text)
    return " ".join(text.split())
