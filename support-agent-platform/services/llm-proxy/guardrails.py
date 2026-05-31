"""Pure guardrail logic (no I/O, no env) — imported by app.py and unit-tested directly.

Defense in depth:
  - mask_pii          : redact emails/cards/phones/SSNs before the prompt leaves to the model
  - detect_injection  : input filter — raw regex PLUS a normalized check that defeats
                        spacing ("i g n o r e") and leetspeak ("1gn0r3")
  - validate_output   : output filter — catch system-prompt leakage in the model's reply

(Regex/keyword filtering is a first layer, not a silver bullet — the red-team harness in
eval/redteam.py measures what still gets through; NER-based PII (Presidio) is the next layer.)
"""
import re

# CARD before PHONE so long digit runs mask as CARD, not PHONE. Order #1234 (<8 digits) is safe.
PII_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE", re.compile(r"\b\+?\d[\d ()-]{7,}\d\b")),
]

# Raw-text patterns (readable, catch the common phrasings).
INJECTION_RE = re.compile(
    r"ignore (all |the )*previous|disregard (the )?(above|previous)|ignore your instructions|"
    r"forget (your |the )?instructions|system prompt|reveal your (system )?prompt|"
    r"print your (full )?(system )?prompt|repeat everything|written above|verbatim|"
    r"you are now|act as (an?|the)|developer mode|unrestricted|jailbreak|\bDAN\b|"
    r"override (the )?(policy|rules|instructions)|reply with exactly|say exactly|"
    r"append the (token|string)|end of ticket|decode this|base64",
    re.I,
)

# Normalized needles: lowercased, leet-folded, all non-alphanumerics stripped — so
# "i g n o r e   previous" and "1gn0r3 pr3v10us" both collapse to "ignoreprevious".
_NORM_NEEDLES = [
    "ignoreall", "ignoreprevious", "ignoreyourinstructions", "ignorethe",
    "disregardabove", "disregardprevious", "forgetinstructions", "forgetyourinstructions",
    "systemprompt", "revealyourprompt", "printyourprompt", "printyoursystemprompt",
    "repeateverything", "writtenabove", "youarenow", "actasan", "actasa",
    "developermode", "unrestricted", "jailbreak", "overridethepolicy", "overridetherules",
    "replywithexactly", "sayexactly", "appendthetoken", "endofticket", "decodethisbase64",
]
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower().translate(_LEET))


def mask_pii(text: str):
    """Return (masked_text, {label: count}) — PII replaced with [LABEL]."""
    counts: dict[str, int] = {}
    for label, pat in PII_PATTERNS:
        def repl(_m, _l=label):
            counts[_l] = counts.get(_l, 0) + 1
            return f"[{_l}]"
        text = pat.sub(repl, text)
    return text, counts


def detect_injection(text: str) -> bool:
    """True if the text looks like a prompt-injection attempt (raw OR normalized match)."""
    if INJECTION_RE.search(text or ""):
        return True
    norm = _normalize(text)
    return any(n in norm for n in _NORM_NEEDLES)


# Phrases from our own system prompt — if the model's OUTPUT contains these, it's leaking.
_LEAK_SIGNATURES = [
    "you are a support agent",
    "knowledge base",
    "use only the knowledge base",
]


def validate_output(text: str) -> tuple[str, bool]:
    """Output filter: if the reply leaks system-prompt content, replace it.
    Returns (safe_text, leaked)."""
    low = (text or "").lower()
    if any(sig in low for sig in _LEAK_SIGNATURES):
        return ("I'm sorry, I can't share that. I can only help with your support request.", True)
    return (text, False)
