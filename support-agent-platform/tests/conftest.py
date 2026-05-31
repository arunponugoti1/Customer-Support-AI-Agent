"""Make the services' pure-logic modules importable (their dirs are hyphenated, so add to path)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("services/llm-proxy", "services/agent", "services/approval"):
    sys.path.insert(0, os.path.join(ROOT, d))
