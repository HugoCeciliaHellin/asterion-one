"""
Asterion One — Disk Queue
============================
Leaf component: no internal dependencies (only stdlib).
Reference: Phase 2, Art.5 §3.1.7 — disk_queue
Reference: Phase 2, Art.4 F3.2 — Store-and-Forward rules

Persistent FIFO queue for messages during communication outages.
Each message is stored as a separate JSON file on disk, named
by sequence ID: {seq_id:06d}.json

This design ensures:
  1. Survives process restarts (disk-backed)
  2. Survives power loss (atomic write via tmp+rename)
  3. Ordered delivery (filenames sort numerically)
  4. Individual ACK/removal (per-message granularity)

Interface contract (IDiskQueue from Art.8 §4):
    enqueue(msg: dict)           → None
    get_from(seq_id: int)        → List[dict]
    remove_up_to(seq_id: int)    → int (count removed)
    depth()                      → int
    is_empty()                   → bool
    peek()                       → Optional[dict]
"""

import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any


class DiskQueue:
    """
    Persistent FIFO queue backed by individual JSON files on disk.

    Each message is stored as {queue_dir}/{seq_id:06d}.json.
    Atomic writes: write to .tmp file, then os.rename() (atomic on Linux).
    """

    def __init__(self, queue_dir: str, max_depth: int = 10000):
        """
        Initialize the disk queue.

        Args:
            queue_dir:  Directory to store queue files.
                        Created if it doesn't exist.
            max_depth:  Maximum number of messages before overflow.
                        Oldest messages are dropped on overflow.
        """
        self._queue_dir = Path(queue_dir)
        self._max_depth = max_depth
        self._lock = threading.Lock()

        # Ensure directory exists
        self._queue_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------
    # Public Interface — IDiskQueue
    # -------------------------------------------------------------------

    def enqueue(self, msg: Dict[str, Any]) -> None:
        """
        Append a message to the queue.

        The message MUST contain a 'seq_id' key (integer) which is
        used as the filename. This is enforced by comms_client which
        assigns monotonic sequence IDs before queuing.

        Args:
            msg: Dict with at least 'seq_id' key. Stored as JSON.

        Raises:
            ValueError: if msg lacks 'seq_id' key.
        """
        if "seq_id" not in msg:
            raise ValueError("Message must contain 'seq_id' key")

        seq_id = int(msg["seq_id"])

        with self._lock:
            # Overflow protection: drop oldest if at capacity
            if self._count_locked() >= self._max_depth:
                self._drop_oldest_locked()

            # Atomic write: tmp file → rename
            final_path = self._queue_dir / f"{seq_id:06d}.json"
            tmp_path = self._queue_dir / f"{seq_id:06d}.json.tmp"

            data = json.dumps(msg, separators=(",", ":"))
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            os.rename(str(tmp_path), str(final_path))

    def get_from(self, seq_id: int) -> List[Dict[str, Any]]:
        """
        Retrieve all messages with seq_id >= the given value.

        Returns messages in ascending seq_id order.
        Does NOT remove them from the queue (non-destructive read).

        Args:
            seq_id: Minimum sequence ID (inclusive).

        Returns:
            List of message dicts, ordered by seq_id ascending.

        Reference: Art.4 F3.2 Rule 4 — REPLAY from last_acked+1
        """
        with self._lock:
            files = self._sorted_files_locked()
            results = []
            for f in files:
                file_seq = self._seq_from_filename(f.name)
                if file_seq is not None and file_seq >= seq_id:
                    msg = self._read_file(f)
                    if msg is not None:
                        results.append(msg)
            return results

    def remove_up_to(self, seq_id: int) -> int:
        """
        Remove all messages with seq_id <= the given value.

        Called when ACK received for a sequence ID — all messages
        up to and including that ID have been delivered successfully.

        Args:
            seq_id: Maximum sequence ID to remove (inclusive).

        Returns:
            Number of files removed.

        Reference: Art.4 F3.2 Rule 3 — pointer advances on ACK
        """
        with self._lock:
            files = self._sorted_files_locked()
            removed = 0
            for f in files:
                file_seq = self._seq_from_filename(f.name)
                if file_seq is not None and file_seq <= seq_id:
                    try:
                        f.unlink()
                        removed += 1
                    except OSError:
                        pass
            return removed

    def depth(self) -> int:
        """Return the number of messages currently in the queue."""
        with self._lock:
            return self._count_locked()

    def is_empty(self) -> bool:
        """Return True if the queue has no messages."""
        return self.depth() == 0

    def peek(self) -> Optional[Dict[str, Any]]:
        """
        Return the oldest message without removing it.

        Returns:
            The message dict with lowest seq_id, or None if empty.
        """
        with self._lock:
            files = self._sorted_files_locked()
            if not files:
                return None
            return self._read_file(files[0])

    def clear(self) -> int:
        """Remove all messages from the queue. Returns count removed."""
        with self._lock:
            files = self._sorted_files_locked()
            removed = 0
            for f in files:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
            return removed

    # -------------------------------------------------------------------
    # Internal Helpers (must hold self._lock)
    # -------------------------------------------------------------------

    def _sorted_files_locked(self) -> List[Path]:
        """List all .json files in the queue dir, sorted by name."""
        try:
            files = [f for f in self._queue_dir.iterdir()
                     if f.suffix == ".json" and not f.name.endswith(".tmp")]
            files.sort(key=lambda f: f.name)
            return files
        except OSError:
            return []

    def _count_locked(self) -> int:
        """Count .json files in the queue dir."""
        return len(self._sorted_files_locked())

    def _drop_oldest_locked(self) -> None:
        """Remove the oldest message (lowest seq_id) for overflow."""
        files = self._sorted_files_locked()
        if files:
            try:
                files[0].unlink()
            except OSError:
                pass

    @staticmethod
    def _seq_from_filename(filename: str) -> Optional[int]:
        """Extract sequence ID from filename like '000042.json'."""
        try:
            return int(filename.replace(".json", ""))
        except ValueError:
            return None

    @staticmethod
    def _read_file(path: Path) -> Optional[Dict[str, Any]]:
        """Read and parse a JSON queue file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (OSError, json.JSONDecodeError):
            return None
