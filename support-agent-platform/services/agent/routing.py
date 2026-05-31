"""Pure routing/classification helpers (no I/O, no env) — imported by app.py, unit-tested."""
import re

INTENTS = ["order_status", "refund", "cancellation", "password_reset", "shipping", "other"]
HIGH_RISK = ("refund", "cancellation")

ORDER_RE = re.compile(r"#?\b(\d{3,})\b")


def extract_order_id(text: str) -> str:
    m = ORDER_RE.search(text or "")
    return m.group(1) if m else "unknown"


def tier_for(intent: str) -> str:
    """Pick a model tier by difficulty/stakes of the ticket (Layer 2 routing)."""
    if intent in HIGH_RISK:        # refund / cancellation — high stakes, strong model
        return "smart"
    if intent == "order_status":   # uses tool data, moderate
        return "balanced"
    return "fast"                  # simple FAQ answers
