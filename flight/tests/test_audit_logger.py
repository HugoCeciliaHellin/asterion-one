"""
Asterion One — audit_logger Unit Tests
========================================
Tests the AuditLogger leaf component.
Reference: Phase 2, Art.5 §3.1.6, Art.8 §2.3 IF-WS-006

Coverage:
  1. Log creates entry with correct fields
  2. First entry has prev_hash = GENESIS
  3. Hash chain links correctly across entries
  4. verify_chain returns valid for correct chain
  5. verify_chain detects tampered entry
  6. verify_chain on empty log returns valid
  7. get_entries returns all entries
  8. get_entries with since filter
  9. Entry count tracks correctly
  10. last_hash updates after each log
  11. Logger survives restart (loads last_hash from file)
  12. Severity enum stored correctly
  13. Metadata stored and retrieved correctly
  14. Stability: 100 entries + verify
  15. Concurrent logging (thread safety)
"""

import sys
import os
import tempfile
import time
import threading
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from flight.audit_logger import AuditLogger
from flight.models import Severity


def make_logger(tmp_dir=None):
    """Create an AuditLogger with a temporary file."""
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()
    log_path = os.path.join(tmp_dir, "audit.jsonl")
    return AuditLogger(log_path=log_path, source="FLIGHT"), log_path


# --- Test 1: Log creates entry with correct fields ---
def test_log_creates_entry():
    logger, _ = make_logger()
    entry = logger.log(
        event_type="STATE_TRANSITION",
        severity=Severity.WARNING,
        description="NOMINAL to SAFE: thermal threshold exceeded",
        metadata={"cpu_temp_c": 78.2},
    )
    assert entry.event_type == "STATE_TRANSITION"
    assert entry.severity == Severity.WARNING
    assert entry.source == "FLIGHT"
    assert "thermal threshold" in entry.description
    assert entry.metadata["cpu_temp_c"] == 78.2
    assert entry.timestamp.tzinfo is not None  # UTC-aware
    assert len(entry.hash) == 64  # SHA-256 hex digest
    assert len(entry.prev_hash) > 0


# --- Test 2: First entry has prev_hash = GENESIS ---
def test_first_entry_genesis():
    logger, _ = make_logger()
    entry = logger.log("BOOT", Severity.INFO, "System booted")
    assert entry.prev_hash == "GENESIS"


# --- Test 3: Hash chain links correctly ---
def test_hash_chain_links():
    logger, _ = make_logger()
    e1 = logger.log("BOOT", Severity.INFO, "Boot started")
    e2 = logger.log("STATE_TRANSITION", Severity.INFO, "BOOT to NOMINAL")
    e3 = logger.log("TELEMETRY_SENT", Severity.INFO, "Frame seq=1")

    # Chain: GENESIS → e1 → e2 → e3
    assert e1.prev_hash == "GENESIS"
    assert e2.prev_hash == e1.hash
    assert e3.prev_hash == e2.hash

    # All hashes are unique
    assert len({e1.hash, e2.hash, e3.hash}) == 3


# --- Test 4: verify_chain returns valid for correct chain ---
def test_verify_valid_chain():
    logger, _ = make_logger()
    logger.log("BOOT", Severity.INFO, "Boot started")
    logger.log("STATE_TRANSITION", Severity.INFO, "BOOT to NOMINAL")
    logger.log("TELEMETRY_SENT", Severity.INFO, "Frame seq=1")

    result = logger.verify_chain()
    assert result.chain_valid is True
    assert result.total_events == 3
    assert result.break_at_index is None


# --- Test 5: verify_chain detects tampered entry ---
def test_verify_detects_tampering():
    logger, log_path = make_logger()
    logger.log("BOOT", Severity.INFO, "Boot started")
    logger.log("STATE_TRANSITION", Severity.INFO, "BOOT to NOMINAL")
    logger.log("TELEMETRY_SENT", Severity.INFO, "Frame seq=1")

    # Tamper with the second entry in the file
    with open(log_path, "r") as f:
        lines = f.readlines()

    # Modify description of line 2 (index 1)
    record = json.loads(lines[1])
    record["description"] = "TAMPERED ENTRY"
    lines[1] = json.dumps(record, separators=(",", ":")) + "\n"

    with open(log_path, "w") as f:
        f.writelines(lines)

    # Re-create logger to read tampered file
    logger2 = AuditLogger(log_path=log_path, source="FLIGHT")
    result = logger2.verify_chain()

    assert result.chain_valid is False
    assert result.break_at_index == 1  # Tampered entry


# --- Test 6: verify_chain on empty log ---
def test_verify_empty_log():
    logger, _ = make_logger()
    result = logger.verify_chain()
    assert result.chain_valid is True
    assert result.total_events == 0


# --- Test 7: get_entries returns all entries ---
def test_get_entries_all():
    logger, _ = make_logger()
    logger.log("E1", Severity.INFO, "First")
    logger.log("E2", Severity.WARNING, "Second")
    logger.log("E3", Severity.CRITICAL, "Third")

    entries = logger.get_entries()
    assert len(entries) == 3
    assert entries[0].event_type == "E1"
    assert entries[1].event_type == "E2"
    assert entries[2].event_type == "E3"


# --- Test 8: get_entries with since filter ---
def test_get_entries_since():
    logger, _ = make_logger()
    logger.log("E1", Severity.INFO, "Old entry")
    time.sleep(0.05)
    cutoff = datetime.now(timezone.utc)
    time.sleep(0.05)
    logger.log("E2", Severity.INFO, "New entry")

    entries = logger.get_entries(since=cutoff)
    assert len(entries) == 1
    assert entries[0].event_type == "E2"


# --- Test 9: entry_count tracks correctly ---
def test_entry_count():
    logger, _ = make_logger()
    assert logger.entry_count == 0
    logger.log("E1", Severity.INFO, "First")
    assert logger.entry_count == 1
    logger.log("E2", Severity.INFO, "Second")
    assert logger.entry_count == 2


# --- Test 10: last_hash updates ---
def test_last_hash_updates():
    logger, _ = make_logger()
    assert logger.last_hash == "GENESIS"

    e1 = logger.log("E1", Severity.INFO, "First")
    assert logger.last_hash == e1.hash

    e2 = logger.log("E2", Severity.INFO, "Second")
    assert logger.last_hash == e2.hash


# --- Test 11: Logger survives restart ---
def test_logger_restart_preserves_chain():
    tmp_dir = tempfile.mkdtemp()
    log_path = os.path.join(tmp_dir, "audit.jsonl")

    # First session: log 3 entries
    logger1 = AuditLogger(log_path=log_path, source="FLIGHT")
    logger1.log("E1", Severity.INFO, "First session entry 1")
    logger1.log("E2", Severity.INFO, "First session entry 2")
    last_hash_session1 = logger1.last_hash

    # "Restart": create new logger instance on same file
    logger2 = AuditLogger(log_path=log_path, source="FLIGHT")

    # Should pick up where session 1 left off
    assert logger2.last_hash == last_hash_session1

    # New entry should chain correctly
    e3 = logger2.log("E3", Severity.INFO, "Second session entry")
    assert e3.prev_hash == last_hash_session1

    # Full chain should verify
    result = logger2.verify_chain()
    assert result.chain_valid is True
    assert result.total_events == 3


# --- Test 12: Severity enum stored correctly ---
def test_severity_stored():
    logger, _ = make_logger()
    logger.log("TEST_INFO", Severity.INFO, "Info event")
    logger.log("TEST_WARN", Severity.WARNING, "Warning event")
    logger.log("TEST_CRIT", Severity.CRITICAL, "Critical event")

    entries = logger.get_entries()
    assert entries[0].severity == Severity.INFO
    assert entries[1].severity == Severity.WARNING
    assert entries[2].severity == Severity.CRITICAL


# --- Test 13: Metadata stored and retrieved ---
def test_metadata_roundtrip():
    logger, _ = make_logger()
    meta = {
        "cpu_temp_c": 78.2,
        "threshold_c": 75.0,
        "state_from": "NOMINAL",
        "state_to": "SAFE",
    }
    logger.log("STATE_TRANSITION", Severity.WARNING, "Temp exceeded", meta)

    entries = logger.get_entries()
    assert entries[0].metadata["cpu_temp_c"] == 78.2
    assert entries[0].metadata["state_from"] == "NOMINAL"


# --- Test 14: Stability — 100 entries + verify ---
def test_stability_100_entries():
    logger, _ = make_logger()
    for i in range(100):
        logger.log(
            f"EVENT_{i:03d}",
            Severity.INFO,
            f"Stability test entry {i}",
            {"iteration": i},
        )

    assert logger.entry_count == 100

    result = logger.verify_chain()
    assert result.chain_valid is True
    assert result.total_events == 100


# --- Test 15: Concurrent logging (thread safety) ---
def test_concurrent_logging():
    logger, _ = make_logger()
    errors = []

    def log_batch(batch_id, count):
        try:
            for i in range(count):
                logger.log(
                    f"THREAD_{batch_id}",
                    Severity.INFO,
                    f"Thread {batch_id}, entry {i}",
                )
        except Exception as e:
            errors.append(e)

    threads = []
    for t_id in range(4):
        t = threading.Thread(target=log_batch, args=(t_id, 25))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    assert len(errors) == 0, f"Errors during concurrent logging: {errors}"
    assert logger.entry_count == 100  # 4 threads × 25 entries

    result = logger.verify_chain()
    assert result.chain_valid is True
    assert result.total_events == 100


# --- Test 16: Log without metadata ---
def test_log_no_metadata():
    logger, _ = make_logger()
    entry = logger.log("SIMPLE", Severity.INFO, "No metadata")
    assert entry.metadata == {}

    entries = logger.get_entries()
    assert entries[0].metadata == {}


# --- Test 17: Hash is deterministic (same input = same hash) ---
def test_hash_deterministic():
    import hashlib
    logger, _ = make_logger()
    entry = logger.log("TEST", Severity.INFO, "Deterministic test")

    # Recompute expected hash
    hash_input = (
        f"{entry.prev_hash}|"
        f"{entry.timestamp.isoformat()}|"
        f"{entry.event_type}|"
        f"{entry.source}|"
        f"{entry.description}"
    )
    expected = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    assert entry.hash == expected
