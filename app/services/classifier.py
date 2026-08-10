"""Search-name classification.

Goal: turn a free product name into a canonical item-type search name so similar
items cluster (BALL BEARING, GASKET, WEAR STRIP…), instead of everyone typing the
full description (95% of the legacy master did exactly that).

Two backends, in priority order:
1. Dictionary match (always available, deterministic, explainable) — matches the
   product name against the canonical SearchTerm vocabulary, most-specific term
   wins (BALL BEARING beats BEARING).
2. LLM (optional, soft dependency) — only consulted when the dictionary has no
   confident hit AND a backend is configured. Never required: the app must run
   with no API key. See llm_backend.py.

Whatever is suggested, a human can edit it before export.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SearchTerm


def _norm(text: str) -> str:
    # keep Thai characters — the master is bilingual and most category words
    # for consumables/hardware are Thai (ตะปู, ลูกปืน, สายไฟ...)
    return re.sub(r"[^a-z0-9฀-๿ ]+", " ", (text or "").lower())


def _tokens(text: str) -> list[str]:
    return [t for t in _norm(text).split() if t]


_THAI = re.compile(r"[฀-๿]")


def suggest_from_dictionary(name: str, terms: list[str]) -> list[tuple[str, float]]:
    """Rank canonical terms that appear in `name`.

    Latin terms match on whole words (so PIN doesn't match PINION); Thai terms
    match as substrings, because Thai is written without spaces between words
    ('งานสอบเทียบเครื่องชั่ง' contains 'งานสอบเทียบ' with no boundary to anchor on).
    Score = length of the matched term, so the most specific term wins.
    """
    name_tokens = _tokens(name)
    if not name_tokens:
        return []
    name_join = " " + " ".join(name_tokens) + " "
    scored: list[tuple[str, float]] = []
    for term in terms:
        t_norm = " ".join(_tokens(term))
        if not t_norm:
            continue
        if _THAI.search(t_norm):
            pos = name_join.find(t_norm)
            matched = pos >= 0
        else:
            phrase = " " + t_norm + " "
            pos = name_join.find(phrase)
            matched = pos >= 0
        if matched:
            # Position first, length second. Thai puts the head noun at the
            # front ('ติดตั้งเครื่องแพ็คกล่อง' is an installation job, not a box),
            # so a term buried later must never outrank one at the start.
            score = (100 - min(pos, 99)) * 10 + len(t_norm)
            scored.append((term, score))
    scored.sort(key=lambda p: p[1], reverse=True)
    # de-duplicate keeping best, cap to 3
    seen, out = set(), []
    for term, score in scored:
        if term in seen:
            continue
        seen.add(term)
        out.append((term, score))
    return out[:3]


def active_terms(db: Session) -> list[str]:
    return list(
        db.scalars(select(SearchTerm.term).where(SearchTerm.active).order_by(SearchTerm.term))
    )


def _neighbour_vote(db: Session, name: str, source: str, terms: list[str]) -> str | None:
    """Ask the item master: what do similar items call themselves?
    Looks up close matches and returns the canonical term most of them share —
    the category is learned from real data instead of guessed."""
    from app.services.snapshots import search_similar

    try:
        hits = search_similar(db, source=source, query=name, limit=10, min_score=0.25)
    except Exception:
        return None
    votes: dict[str, int] = {}
    for item, _score in hits:
        for term, _s in suggest_from_dictionary(item.name, terms):
            votes[term] = votes.get(term, 0) + 1
            break  # only the best term per neighbour
    if not votes:
        return None
    best, count = max(votes.items(), key=lambda kv: kv[1])
    return best if count >= 2 else None


SERVICE_TERMS = frozenset({
    "งานสอบเทียบ", "งานซ่อม", "งานติดตั้ง", "ค่าบริการ", "ค่าเช่า", "ค่าขนส่ง",
    "ติดตั้ง", "ซ่อม", "ซ่อมแซม", "สอบเทียบ", "ปรับปรุง", "บำรุงรักษา",
    "ตรวจสอบ", "ทำความสะอาด", "เช่า", "ขนส่ง", "ก่อสร้าง", "ต่อเติม",
    "รื้อถอน", "ออกแบบ", "ที่ปรึกษา", "ฝึกอบรม", "จ้างเหมา",
})


def classify(
    db: Session,
    name: str,
    *,
    llm=None,
    snapshot_source: str | None = None,
    product_type: str | None = None,
) -> dict:
    """Return {'suggestion', 'source', 'candidates'}.
    source ∈ {'dictionary','neighbours','llm','fallback'}.

    `name` should be the BASE item name only — passing brand/model in produces
    nonsense categories ('ตะปู XXX #12345' -> 'XXX 12345').

    `product_type` is the chosen sub-category's type. For a Service the search
    name must name the WORK, not an object mentioned in passing:
    'ติดตั้งเครื่องแพ็คกล่อง' is an installation job, not a box.
    """
    terms = active_terms(db)
    if (product_type or "").lower() == "service":
        service_only = [t for t in terms if t in SERVICE_TERMS]
        hits = suggest_from_dictionary(name, service_only)
        if hits:
            return {
                "suggestion": hits[0][0],
                "source": "dictionary",
                "candidates": [t for t, _ in hits],
            }
        # no known service verb: keep the leading words, which in Thai carry
        # the action, rather than a noun from the end of the phrase
        head = " ".join(_tokens(name)[:3])
        return {
            "suggestion": (head or name)[:60],
            "source": "fallback",
            "candidates": [],
        }

    dict_hits = suggest_from_dictionary(name, terms)
    if dict_hits:
        return {
            "suggestion": dict_hits[0][0],
            "source": "dictionary",
            "candidates": [t for t, _ in dict_hits],
        }
    if snapshot_source:
        voted = _neighbour_vote(db, name, snapshot_source, terms)
        if voted:
            return {"suggestion": voted, "source": "neighbours", "candidates": [voted]}
    if llm is not None:
        try:
            picked = llm(name, terms)
        except Exception:
            picked = None
        if picked:
            return {"suggestion": picked, "source": "llm", "candidates": [picked]}
    # Fallback: the base name itself, cleaned — for 'ตะปู' that IS the category.
    cleaned = " ".join(_tokens(name)[:3])
    fallback = cleaned.upper() if cleaned else (name or "")[:60]
    return {"suggestion": fallback, "source": "fallback", "candidates": []}


def promote_term(db: Session, term: str) -> SearchTerm:
    """Add a new canonical term (or bump usage of an existing one)."""
    term = " ".join(term.split()).upper()[:60]
    existing = db.scalar(select(SearchTerm).where(SearchTerm.term == term))
    if existing:
        existing.usage_count += 1
        existing.active = True
        db.commit()
        return existing
    st = SearchTerm(term=term, usage_count=1)
    db.add(st)
    db.commit()
    return st
