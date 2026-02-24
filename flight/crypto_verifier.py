"""
Asterion One — Crypto Verifier
=================================
Leaf component: no internal dependencies.
Reference: Phase 2, Art.5 §3.1.4 — crypto_verifier
Reference: Phase 2, Art.8 §2.3 IF-WS-002 — Canonical JSON for signing

Verifies Ed25519 digital signatures on command plans.
This is the Flight-side security gate: every PLAN_UPLOAD message
must pass signature verification before commands are executed.

Signing happens on the Ground UI (browser-side, tweetnacl-js).
Verification happens here on the Flight Segment (Python).

SECURITY DESIGN [REQ-SEC-ED25519]:
  1. Ground signs: SHA256(canonical_json(commands)) → Ed25519.sign(hash, private_key)
  2. Flight verifies: Ed25519.verify(signature, hash, public_key)
  3. If verification fails: NACK + 2 CRITICAL audit events

Canonical JSON specification [Art.8 §2.3 IF-WS-002]:
  canonical = json.dumps(commands, sort_keys=True, separators=(',', ':'))
  hash = SHA256(canonical.encode('utf-8'))

Trusted keys are loaded from a JSON file on disk.

Interface contract (ICryptoVerifier from Art.8 §4):
    verify(plan_data) → bool
    get_trusted_keys() → List[bytes]
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
    Ed25519PrivateKey,
)
from cryptography.exceptions import InvalidSignature

from flight.config import FswConfig


class CryptoVerifier:
    """
    Verifies Ed25519 signatures on command plans.

    Trusted public keys are loaded from a JSON file.
    Format: [{"name": "operator1", "public_key_hex": "aabbcc..."}]
    """

    def __init__(self, config: Optional[FswConfig] = None):
        """
        Initialize the crypto verifier.

        Args:
            config: Flight configuration (for trusted_keys_path).
                    Uses defaults if None.
        """
        self._config = config or FswConfig()
        self._trusted_keys: Dict[str, bytes] = {}
        self._load_trusted_keys()

    # -------------------------------------------------------------------
    # Public Interface — ICryptoVerifier
    # -------------------------------------------------------------------

    def verify(self, plan_data: Dict[str, Any]) -> bool:
        """
        Verify the Ed25519 signature on a command plan.

        Args:
            plan_data: Dict containing:
                commands:    List[Dict] — the commands array
                signature:   str — hex-encoded Ed25519 signature
                public_key:  str — hex-encoded Ed25519 public key

        Returns:
            True if signature is valid AND public_key is trusted.
            False otherwise.

        Reference: Art.8 §2.3 IF-WS-002 — PLAN_UPLOAD verification
        """
        try:
            commands = plan_data.get("commands", [])
            signature_hex = plan_data.get("signature", "")
            public_key_hex = plan_data.get("public_key", "")

            if not commands or not signature_hex or not public_key_hex:
                return False

            # Check if public key is trusted
            public_key_bytes = bytes.fromhex(public_key_hex)
            if not self.is_trusted_key(public_key_bytes):
                return False

            # Compute canonical hash
            canonical_hash = self.compute_canonical_hash(commands)

            # Verify Ed25519 signature
            signature_bytes = bytes.fromhex(signature_hex)
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            public_key.verify(signature_bytes, canonical_hash)

            return True

        except (ValueError, InvalidSignature, Exception):
            return False

    def is_trusted_key(self, public_key_bytes: bytes) -> bool:
        """
        Check if a public key is in the trusted keys list.

        Args:
            public_key_bytes: Raw Ed25519 public key (32 bytes).

        Returns:
            True if the key is trusted, False otherwise.
        """
        key_hex = public_key_bytes.hex()
        return key_hex in self._trusted_keys

    def get_trusted_keys(self) -> List[bytes]:
        """
        Return all trusted public keys.

        Returns:
            List of raw public key bytes.
        """
        return [bytes.fromhex(k) for k in self._trusted_keys.keys()]

    def add_trusted_key(self, name: str, public_key_bytes: bytes) -> None:
        """
        Add a trusted public key at runtime.

        Args:
            name: Human-readable identifier (e.g., "operator1").
            public_key_bytes: Raw Ed25519 public key (32 bytes).
        """
        self._trusted_keys[public_key_bytes.hex()] = name

    def remove_trusted_key(self, public_key_bytes: bytes) -> None:
        """Remove a trusted public key."""
        self._trusted_keys.pop(public_key_bytes.hex(), None)

    # -------------------------------------------------------------------
    # Static Methods — Canonical JSON + Hash
    # -------------------------------------------------------------------

    @staticmethod
    def compute_canonical_hash(commands: List[Dict[str, Any]]) -> bytes:
        """
        Compute the canonical hash of a commands array.

        This is the value that gets signed/verified.
        Both Ground (JS) and Flight (Python) MUST produce identical output.

        Steps:
          1. Serialize commands with sorted keys, compact separators
          2. Encode as UTF-8
          3. Compute SHA-256 digest

        Args:
            commands: List of command dicts.

        Returns:
            SHA-256 digest bytes (32 bytes).

        Reference: Art.8 §2.3 IF-WS-002 — Canonical JSON specification
        """
        canonical = json.dumps(commands, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).digest()

    @staticmethod
    def compute_canonical_hash_hex(commands: List[Dict[str, Any]]) -> str:
        """Same as compute_canonical_hash but returns hex string."""
        return CryptoVerifier.compute_canonical_hash(commands).hex()

    # -------------------------------------------------------------------
    # Key Generation (for testing / initial setup)
    # -------------------------------------------------------------------

    @staticmethod
    def generate_keypair() -> tuple:
        """
        Generate a new Ed25519 keypair.

        Returns:
            (private_key_bytes, public_key_bytes) — both raw bytes.

        For testing and initial operator key setup only.
        In production, keys would be generated offline.
        """
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_bytes = private_key.private_bytes_raw()
        public_bytes = public_key.public_bytes_raw()

        return private_bytes, public_bytes

    @staticmethod
    def sign(commands: List[Dict[str, Any]], private_key_bytes: bytes) -> bytes:
        """
        Sign a commands array with an Ed25519 private key.

        This method exists for testing. In production, signing
        happens on the Ground UI (browser-side, tweetnacl-js).

        Args:
            commands: List of command dicts.
            private_key_bytes: Raw Ed25519 private key (32 bytes).

        Returns:
            Raw Ed25519 signature bytes (64 bytes).
        """
        canonical_hash = CryptoVerifier.compute_canonical_hash(commands)
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        return private_key.sign(canonical_hash)

    # -------------------------------------------------------------------
    # Internal — Key Loading
    # -------------------------------------------------------------------

    def _load_trusted_keys(self) -> None:
        """Load trusted keys from config file (if it exists)."""
        key_path = Path(self._config.TRUSTED_KEYS_PATH)

        if not key_path.exists():
            return

        try:
            with open(key_path, "r", encoding="utf-8") as f:
                keys_data = json.loads(f.read())

            for entry in keys_data:
                name = entry.get("name", "unknown")
                key_hex = entry.get("public_key_hex", "")
                if key_hex:
                    self._trusted_keys[key_hex] = name
        except (json.JSONDecodeError, OSError):
            pass
