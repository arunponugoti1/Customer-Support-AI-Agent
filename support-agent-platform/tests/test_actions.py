"""Unit tests for the approval action logic (the refund/cancellation sandbox)."""
import pytest

import actions


def test_refund_executes_with_confirmation():
    r = actions.execute_action("refund", {"order_id": "4471", "amount_usd": 50})
    assert r["status"] == "issued"
    assert r["order_id"] == "4471"
    assert r["confirmation"].startswith("RF-")


def test_cancellation_executes():
    r = actions.execute_action("cancellation", {"order_id": "8830"})
    assert r["status"] == "cancelled"
    assert r["confirmation"].startswith("CX-")


def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        actions.execute_action("delete_account", {})


def test_action_sets():
    assert actions.INLINE_EXECUTE == {"refund", "cancellation"}
    assert "send_email" in actions.ALLOWED_ACTIONS
    # send_email must NOT be inline-executed by the approval service (no creds there)
    assert "send_email" not in actions.INLINE_EXECUTE
