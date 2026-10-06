"""Append-only local Trading Journal storage using JSON Lines (.jsonl)."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Union
from atsits.journal.models import (
    JournalRecord,
    JournalRecordType,
    TradeRecord,
    deserialize_journal_record,
)


class TradingJournal:
    """Local, append-only factual trading journal backed by JSON Lines (.jsonl).

    Provides factual system-of-record logging and flexible querying without
    introducing external database dependencies.
    """

    def __init__(self, file_path: Optional[Union[str, Path]] = None):
        self.file_path: Optional[Path] = Path(file_path).resolve() if file_path else None
        self._records: List[JournalRecord] = []

        if self.file_path:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            if self.file_path.is_file():
                self._load_from_file()

    def _load_from_file(self) -> None:
        """Load records from the existing .jsonl file."""
        if not self.file_path or not self.file_path.is_file():
            return

        self._records.clear()
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, start=1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                try:
                    record = deserialize_journal_record(clean_line)
                    self._records.append(record)
                except Exception as err:
                    raise ValueError(
                        f"Malformed journal line #{line_idx} in '{self.file_path}': {err}"
                    ) from err

    def append(self, record: JournalRecord) -> None:
        """Append a single factual record to the journal and file."""
        self._records.append(record)
        if self.file_path:
            line_json = record.model_dump_json()
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(line_json + "\n")

    def append_many(self, records: Sequence[JournalRecord]) -> None:
        """Append a sequence of factual records to the journal and file."""
        for r in records:
            self.append(r)

    def read_all(self) -> List[JournalRecord]:
        """Return all recorded journal records."""
        return list(self._records)

    def count(self) -> int:
        """Return total number of records."""
        return len(self._records)

    def filter_records(
        self,
        symbol: Optional[str] = None,
        strategy_version: Optional[str] = None,
        record_type: Optional[Union[JournalRecordType, str]] = None,
        trade_id: Optional[str] = None,
        run_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[JournalRecord]:
        """Filter journal records based on multiple factual criteria."""
        type_val = record_type.value if isinstance(record_type, JournalRecordType) else record_type

        filtered: List[JournalRecord] = []
        for r in self._records:
            if symbol is not None and r.symbol != symbol:
                continue
            if strategy_version is not None and r.strategy_version != strategy_version:
                continue
            if type_val is not None and r.record_type.value != type_val:
                continue
            if run_id is not None and r.run_id != run_id:
                continue
            if start_time is not None and r.timestamp < start_time:
                continue
            if end_time is not None and r.timestamp > end_time:
                continue

            if trade_id is not None:
                # Check trade_id attribute if present on record type
                rec_trade_id = getattr(r, "trade_id", None)
                if rec_trade_id != trade_id:
                    continue

            filtered.append(r)

        return filtered

    def get_trade_lifecycle(self, trade_id: str) -> List[JournalRecord]:
        """Retrieve the complete factual lifecycle records for a specific trade.

        Matches records with the matching trade_id or setup records directly associated
        with the trade.
        """
        lifecycle: List[JournalRecord] = []
        for r in self._records:
            if getattr(r, "trade_id", None) == trade_id:
                lifecycle.append(r)
        return lifecycle

    def get_trades(self, run_id: Optional[str] = None) -> List[TradeRecord]:
        """Retrieve all completed TradeRecord instances, optionally filtered by run_id."""
        trades: List[TradeRecord] = []
        for r in self._records:
            if isinstance(r, TradeRecord):
                if run_id is None or r.run_id == run_id:
                    trades.append(r)
        return trades
