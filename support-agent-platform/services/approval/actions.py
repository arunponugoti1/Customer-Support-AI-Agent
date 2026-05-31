"""Pure action logic for the approval gate (no I/O, no env) — imported by app.py, unit-tested.

  - INLINE_EXECUTE: the approval service runs these itself on approve (it owns the capability).
  - others (e.g. send_email): approved here, executed by an external worker (gmail-connector)
    that owns the credential, which then calls /complete.
"""
import uuid

INLINE_EXECUTE = {"refund", "cancellation"}
ALLOWED_ACTIONS = INLINE_EXECUTE | {"send_email"}


def execute_action(action_type: str, payload: dict) -> dict:
    """Perform the approved action. Reached ONLY for a row already in status 'approved'
    (enforced by the caller). Layer 3 has no real payment API, so refund/cancel are
    deterministic stand-ins — but the *gating* is the real point."""
    if action_type == "refund":
        return {"status": "issued", "kind": "refund",
                "order_id": payload.get("order_id"),
                "amount_usd": payload.get("amount_usd"),
                "confirmation": f"RF-{uuid.uuid4().hex[:10].upper()}"}
    if action_type == "cancellation":
        return {"status": "cancelled", "kind": "cancellation",
                "order_id": payload.get("order_id"),
                "confirmation": f"CX-{uuid.uuid4().hex[:10].upper()}"}
    raise ValueError(f"unsupported action_type: {action_type}")
