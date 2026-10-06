"""Unit tests for JournalEntry model ensuring fact/interpretation separation and immutability."""

import json
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from atsits.models.journal import JournalEntry


def test_pure_system_facts_journal_entry():
    """Verify journal entry containing strictly deterministic system facts."""
    now = datetime.now(timezone.utc)
    entry = JournalEntry(
        entry_id="jrn-001",
        timestamp=now,
        event_type="TRADE_FILLED",
        system_facts={
            "trade_id": "trd-001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "fill_price": 50000.0,
            "quantity": 0.5,
            "commission": 1.0,
        },
    )
    assert entry.entry_id == "jrn-001"
    assert entry.gemini_notes is None
    assert entry.system_facts["fill_price"] == 50000.0


def test_journal_entry_with_gemini_notes():
    """Verify journal entry with separate Gemini qualitative notes."""
    now = datetime.now(timezone.utc)
    entry = JournalEntry(
        entry_id="jrn-002",
        timestamp=now,
        event_type="SETUP_REJECTED",
        system_facts={
            "symbol": "BTCUSDT",
            "reason": "RISK_LIMIT_EXCEEDED",
            "max_positions": 1,
            "current_positions": 1,
        },
        gemini_notes="Trade setup was valid on EMA criteria but rejected due to max position limits.",
    )
    assert entry.gemini_notes is not None
    assert "rejected due to max position" in entry.gemini_notes
    assert entry.system_facts["reason"] == "RISK_LIMIT_EXCEEDED"


def test_journal_entry_immutability():
    """Verify JournalEntry cannot be mutated after creation."""
    entry = JournalEntry(
        entry_id="jrn-003",
        timestamp=datetime.now(timezone.utc),
        event_type="TEST_EVENT",
        system_facts={"test": True},
    )
    with pytest.raises(ValidationError):
        entry.event_type = "MUTATED"  # type: ignore


def test_journal_entry_system_facts_nested_immutability():
    """Verify that system_facts dictionary cannot be mutated in place (top-level or nested)."""
    raw_facts = {
        "trade_id": "trd-100",
        "fill_price": 50000.0,
        "details": {
            "slippage": 0.25,
            "sub_detail": {"fee": 1.5},
        },
    }
    entry = JournalEntry(
        entry_id="jrn-004",
        timestamp=datetime.now(timezone.utc),
        event_type="TRADE_FILLED",
        system_facts=raw_facts,
    )

    # 1. Attempt top-level mutation
    with pytest.raises(TypeError, match="does not support item assignment"):
        entry.system_facts["fill_price"] = 99999.0  # type: ignore

    with pytest.raises(TypeError, match="does not support item assignment"):
        entry.system_facts["new_key"] = "forbidden"  # type: ignore

    # 2. Attempt nested dictionary mutation
    with pytest.raises(TypeError, match="does not support item assignment"):
        entry.system_facts["details"]["slippage"] = 999.0  # type: ignore

    with pytest.raises(TypeError, match="does not support item assignment"):
        entry.system_facts["details"]["sub_detail"]["fee"] = 999.0  # type: ignore

    # 3. Verify original input dict mutation does not affect the model
    raw_facts["fill_price"] = 12345.0
    assert entry.system_facts["fill_price"] == 50000.0


def test_journal_entry_json_serialization():
    """Verify that JournalEntry with frozen system_facts serializes to JSON cleanly."""
    now = datetime.now(timezone.utc)
    entry = JournalEntry(
        entry_id="jrn-005",
        timestamp=now,
        event_type="TRADE_FILLED",
        system_facts={"fill_price": 50000.0, "nested": {"fee": 1.0}},
        gemini_notes="Observation note",
    )

    # Test model_dump
    dumped = entry.model_dump()
    assert isinstance(dumped["system_facts"], dict)
    assert dumped["system_facts"]["nested"]["fee"] == 1.0

    # Test standard json.dumps
    json_str = entry.model_dump_json()
    assert '"fill_price":50000.0' in json_str or '"fill_price": 50000.0' in json_str

    # Test reconstruct round-trip
    reconstructed = JournalEntry.model_validate(json.loads(json_str))
    assert reconstructed.entry_id == entry.entry_id
    assert reconstructed.system_facts["fill_price"] == 50000.0
    assert reconstructed.gemini_notes == "Observation note"
