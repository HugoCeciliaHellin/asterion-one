"""
Asterion One — Audit Logger
==============================
Leaf component: no internal dependencies (only stdlib).
Reference: Phase 2, Art.5 §3.1.6 — audit_logger
Reference: Phase 2, Art.8 §2.3 IF-WS-006 — hash computation

Implements a persistent, hash-chained audit log that records every
significant event in the Flight Software. The chain makes the log
tamper-evident: modifying any entry breaks the chain.

Hash computation [REQ-FSW-LOG-SECURE]:
    hash = SHA256(prev_hash || timestamp || event_type || source || description)
Where || denotes string concatenation with '|' separator.

First record: prev_hash = "GENESIS"

Storage: JSONL (JSON Lines) file — one JSON object per line.
This format is append-only, crash-safe (partial writes are
truncated lines that can be detected), and grep-friendly.

Interface contract (IAuditLog from Art.8 §4):
    log(event_type, severity, description, metadata) → AuditEntry
    verify_chain() → ChainVerificationResult
    get_entries(since=None) → List[AuditEntry]
"""

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from flight.models import AuditEntry, ChainVerificationResult, Severity


class AuditLogger:
    """
    Persistent, hash-chained audit log for the Flight Segment.

    Every call to log() appends an entry with:
      - SHA-256 hash linking to previous entry
      - ISO 8601 UTC timestamp
      - Event type, source, severity, description, metadata

    The chain can be verified at any time via verify_chain().
    """

    # The "prev_hash" value for the very first entry in the chain
    GENESIS_HASH = "GENESIS"

    def __init__(self, log_path: str, source: str = "FLIGHT"):
        """
        Initialize the audit logger.

        Args:
            log_path: Path to the JSONL audit log file.
                      Parent directories are created if needed.
            source:   Default source identifier for events.
                      Typically "FLIGHT" for the Flight Segment.
        """
        self._log_path = Path(log_path)
        self._source = source
        self._lock = threading.Lock()

        # Ensure parent directory exists
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        # Load the last hash from existing log (or GENESIS if empty/new)
        self._prev_hash = self._load_last_hash()

    # -------------------------------------------------------------------
    # Public Interface — IAuditLog
    # -------------------------------------------------------------------

    def log(
        self,
        event_type: str,
        severity: Severity,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """
        Append a new entry to the hash-chained audit log.

        Args:
            event_type:  Machine-readable type string.
                         Examples: STATE_TRANSITION, WATCHDOG_RESTART,
                         COMMAND_EXECUTED, SIGNATURE_INVALID, OUTAGE_START
            severity:    INFO, WARNING, or CRITICAL
            description: Human-readable description of the event.
            metadata:    Optional structured data (must be JSON-serializable).

        Returns:
            The AuditEntry that was appended (with hash and prev_hash set).

        Thread-safe: serialized via internal lock.
        """
        metadata = metadata or {}
        timestamp = datetime.now(timezone.utc)

        with self._lock:
            # Compute hash: SHA256(prev_hash|timestamp|event_type|source|description)
            hash_input = (
                f"{self._prev_hash}|"
                f"{timestamp.isoformat()}|"
                f"{event_type}|"
                f"{self._source}|"
                f"{description}"
            )
            entry_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            # Create the entry
            entry = AuditEntry(
                timestamp=timestamp,
                event_type=event_type,
                source=self._source,
                severity=severity,
                description=description,
                metadata=metadata,
                hash=entry_hash,
                prev_hash=self._prev_hash,
            )

            # Append to file (atomic-ish: single write + flush)
            self._append_to_file(entry)

            # Update chain pointer
            self._prev_hash = entry_hash

            return entry

    def verify_chain(self) -> ChainVerificationResult:
        """
        Verify the integrity of the entire hash chain.

        Reads all entries from the log file and recomputes each hash.
        If any hash doesn't match, reports the break point.

        Returns:
            ChainVerificationResult with chain_valid, total_events,
            and break_at_index if chain is broken.
        """
        entries = self._read_all_entries()

        if len(entries) == 0:
            return ChainVerificationResult(
                chain_valid=True,
                total_events=0,
            )

        prev_hash = self.GENESIS_HASH

        for i, entry in enumerate(entries):
            # Check prev_hash linkage
            if entry.prev_hash != prev_hash:
                return ChainVerificationResult(
                    chain_valid=False,
                    total_events=len(entries),
                    break_at_index=i,
                    expected_hash=prev_hash,
                    actual_hash=entry.prev_hash,
                )

            # Recompute hash
            hash_input = (
                f"{entry.prev_hash}|"
                f"{entry.timestamp.isoformat()}|"
                f"{entry.event_type}|"
                f"{entry.source}|"
                f"{entry.description}"
            )
            expected = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            if entry.hash != expected:
                return ChainVerificationResult(
                    chain_valid=False,
                    total_events=len(entries),
                    break_at_index=i,
                    expected_hash=expected,
                    actual_hash=entry.hash,
                )

            prev_hash = entry.hash

        return ChainVerificationResult(
            chain_valid=True,
            total_events=len(entries),
        )

    def get_entries(
        self, since: Optional[datetime] = None
    ) -> List[AuditEntry]:
        """
        Retrieve audit entries, optionally filtered by timestamp.

        Args:
            since: If provided, only return entries with timestamp >= since.
                   If None, return all entries.

        Returns:
            List of AuditEntry objects in chronological order.
        """
        entries = self._read_all_entries()

        if since is not None:
            # Ensure timezone-aware comparison
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            entries = [e for e in entries if e.timestamp >= since]

        return entries

    @property
    def last_hash(self) -> str:
        """The hash of the most recent entry (or GENESIS if empty)."""
        with self._lock:
            return self._prev_hash

    @property
    def entry_count(self) -> int:
        """Total number of entries in the log."""
        return len(self._read_all_entries())

    # -------------------------------------------------------------------
    # Internal — File I/O
    # -------------------------------------------------------------------

    def _append_to_file(self, entry: AuditEntry) -> None:
        """Append a single entry as a JSON line to the log file."""
        record = {
            "timestamp": entry.timestamp.isoformat(),
            "event_type": entry.event_type,
            "source": entry.source,
            "severity": entry.severity.value,
            "description": entry.description,
            "metadata": entry.metadata,
            "hash": entry.hash,
            "prev_hash": entry.prev_hash,
        }
        line = json.dumps(record, separators=(",", ":")) + "\n"

        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _read_all_entries(self) -> List[AuditEntry]:
        """Read all entries from the log file."""
        entries = []

        if not self._log_path.exists():
            return entries

        with open(self._log_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    entry = AuditEntry(
                        timestamp=datetime.fromisoformat(record["timestamp"]),
                        event_type=record["event_type"],
                        source=record["source"],
                        severity=Severity(record["severity"]),
                        description=record["description"],
                        metadata=record.get("metadata", {}),
                        hash=record["hash"],
                        prev_hash=record["prev_hash"],
                    )
                    entries.append(entry)
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    # Corrupted line — skip but could log warning
                    pass

        return entries

    def _load_last_hash(self) -> str:
        """Load the hash of the last entry, or GENESIS if log is empty."""
        entries = self._read_all_entries()
        if entries:
            return entries[-1].hash
        return self.GENESIS_HASH
