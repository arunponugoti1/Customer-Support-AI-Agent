"""Unit tests for the agent routing helpers (order extraction + model tiering)."""
import pytest

import routing


@pytest.mark.parametrize("text,expected", [
    ("Where is my order #4471?", "4471"),
    ("status of order 1290 please", "1290"),
    ("track package 5512", "5512"),
    ("I want a refund", "unknown"),
    ("", "unknown"),
])
def test_extract_order_id(text, expected):
    assert routing.extract_order_id(text) == expected


@pytest.mark.parametrize("intent,tier", [
    ("refund", "smart"),
    ("cancellation", "smart"),
    ("order_status", "balanced"),
    ("shipping", "fast"),
    ("password_reset", "fast"),
    ("other", "fast"),
])
def test_tier_for(intent, tier):
    assert routing.tier_for(intent) == tier


def test_high_risk_set():
    assert set(routing.HIGH_RISK) == {"refund", "cancellation"}
    # every high-risk intent must route to the strong model
    for intent in routing.HIGH_RISK:
        assert routing.tier_for(intent) == "smart"
