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
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())


def _tokens(text: str) -> list[str]:
    return [t for t in _norm(text).split() if t]


def suggest_from_dictionary(name: str, terms: list[str]) -> list[tuple[str, float]]:
    """Rank canonical terms that appear in `name`. Score favours more specific
    (multi-word) terms and earlier position in the name."""
    name_tokens = _tokens(name)
    if not name_tokens:
        return []
    name_join = " " + " ".join(name_tokens) + " "
    scored: list[tuple[str, float]] = []
    for term in terms:
        t_tokens = _tokens(term)
        if not t_tokens:
            continue
        phrase = " " + " ".join(t_tokens) + " "
        if phrase in name_join:
            pos = name_join.index(phrase)
            # specificity (word count) dominates; earlier position breaks ties
            score = len(t_tokens) * 10 - pos / 100.0
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


def classify(db: Session, name: str, *, llm=None) -> dict:
    """Return {'suggestion', 'source', 'candidates'}.
    source ∈ {'dictionary','llm','fallback'}. Always returns something usable."""
    terms = active_terms(db)
    dict_hits = suggest_from_dictionary(name, terms)
    if dict_hits:
        return {
            "suggestion": dict_hits[0][0],
            "source": "dictionary",
            "candidates": [t for t, _ in dict_hits],
        }
    if llm is not None:
        try:
            picked = llm(name, terms)
        except Exception:
            picked = None
        if picked:
            return {"suggestion": picked, "source": "llm", "candidates": [picked]}
    # Fallback: first meaningful tokens, upper-cased (better than the full string).
    toks = _tokens(name)
    fallback = " ".join(toks[:2]).upper() if toks else (name or "")[:60]
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
