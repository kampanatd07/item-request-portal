"""Optional LLM backend for search-name classification.

Soft dependency by design: if ANTHROPIC_API_KEY is unset or the `anthropic`
package is not installed, `get_llm()` returns None and the classifier falls back
to the dictionary. The deployed app never hard-fails without a key.
"""

import os


def get_llm():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic(api_key=api_key)

    def llm(name: str, candidates: list[str]) -> str | None:
        prompt = (
            "You normalize purchase-item names into a short canonical item-type "
            "search name (2-3 words, uppercase), grouping similar items.\n"
            f"Existing canonical terms (prefer reusing one if it fits): "
            f"{', '.join(candidates[:80])}\n\n"
            f"Item name: {name}\n"
            "Reply with ONLY the search name, nothing else."
        )
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip().strip('"')
            return text[:60] or None
        except Exception:
            return None

    return llm
