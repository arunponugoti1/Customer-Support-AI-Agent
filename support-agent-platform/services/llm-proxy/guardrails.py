"""Pure guardrail logic (no I/O, no env) — imported by app.py and unit-tested directly.

PII masking + prompt-injection detection for the Layer 2 app-security layer.
"""
import re

# CARD before PHONE so long digit runs mask as CARD, not PHONE. Order #1234 (<8 digits) is safe.
PII_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE", re.compile(r"\b\+?\d[\d ()-]{7,}\d\b")),
]
INJECTION_RE = re.compile(
    r"ignore (all )?(the )?previous|disregard (the )?(above|previous)|ignore your instructions|"
    r"forget (your |the )?instructions|system prompt|reveal your (system )?prompt|"
    r"you are now|act as (an?|the)|override (the )?(policy|rules|instructions)",
    re.I,
)


def mask_pii(text: str):
    """Return (masked_text, {label: count}) — emails/cards/phones replaced with [LABEL]."""
    counts: dict[str, int] = {}
    for label, pat in PII_PATTERNS:
        def repl(_m, _l=label):
            counts[_l] = counts.get(_l, 0) + 1
            return f"[{_l}]"
        text = pat.sub(repl, text)
    return text, counts


def detect_injection(text: str) -> bool:
    """True if the text looks like a prompt-injection attempt."""
    return bool(INJECTION_RE.search(text or ""))
