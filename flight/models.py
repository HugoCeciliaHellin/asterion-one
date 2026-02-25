"""
Asterion One — Flight Segment Data Models
==========================================
Canonical data types shared across all Flight Segment components.
Reference: Phase 2, Artifact 8 (ICD) §4.2 — Data Models

These dataclasses define the contracts between components.
Any component that imports from here is guaranteed type-safe
interoperability with the rest of the Flight Segment.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class FswState(str, Enum):
    """
    Flight Software operational states.
    Reference: Art.3 §2 — State Machine Definition

    BOOT     → Initial startup, self-test running
    NOMINAL  → Full operations, all subsystems active
    SAFE     → Reduced operations, fault detected
    CRITICAL → Ceased operations, manual restart required
    """
    BOOT = "BOOT"
    NOMINAL = "NOMINAL"
    SAFE = "SAFE"
    CRITICAL = "CRITICAL"


class Severity(str, Enum):
    """
    Audit event severity levels.
    Reference: Art.2 §3.5 — audit_events.severity
    """
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class CommandStatus(str, Enum):
    """
    Lifecycle status of a command.
    Reference: Art.2 §3.3 — commands.status
    """
    QUEUED = "QUEUED"
    SENT = "SENT"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PlanStatus(str, Enum):
    """
    Lifecycle status of a command plan.
    Reference: Art.2 §3.2 — command_plans.status
    """
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    UPLOADED = "UPLOADED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class WindowStatus(str, Enum):
    """
    Contact window lifecycle status.
    Reference: Art.2 §3.1 — contact_windows.status
    """
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

@dataclass
class TelemetryFrame:
    """
    A single telemetry snapshot from all subsystems.
    Reference: Art.8 §2.3 — IF-WS-001 (TELEMETRY message payload)

    Fields:
        seq_id:     Monotonic sequence ID [REQ-COM-ZERO-LOSS]
        timestamp:  UTC timestamp of frame generation
        fsw_state:  Current FSW state at time of generation
        subsystems: Dict mapping subsystem name → metrics dict
                    Keys: THERMAL, POWER, CPU, COMMS, FSW
                    Reference: Art.5 §3.1.5 — sensor_sim subsystems
    """
    seq_id: int
    timestamp: datetime
    fsw_state: FswState
    subsystems: Dict[str, Dict[str, float]]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@dataclass
class Command:
    """
    A single command within a command plan.
    Reference: Art.8 §2.3 — IF-WS-002 (PLAN_UPLOAD commands array)

    Fields:
        sequence_id:  Order within the plan (1, 2, 3, ...)
        command_type: Type identifier (SET_PARAM, RUN_DIAGNOSTIC, SET_MODE, etc.)
        payload:      Type-specific parameters
    """
    sequence_id: int
    command_type: str
    payload: Dict[str, Any]


@dataclass
class CommandPlan:
    """
    A signed collection of commands for upload to the Flight Segment.
    Reference: Art.8 §2.3 — IF-WS-002 (PLAN_UPLOAD)

    Fields:
        plan_id:        UUID v4 identifier
        commands:       Ordered list of commands
        signature:      Ed25519 signature bytes (base64 when serialized)
        signature_algo: Always "Ed25519" [REQ-SEC-ED25519]
        public_key:     Ed25519 public key bytes (base64 when serialized)
    """
    plan_id: str
    commands: List[Command]
    signature: bytes
    signature_algo: str = "Ed25519"
    public_key: bytes = b""


@dataclass
class PlanResult:
    """
    Result of executing a command plan on the Flight Segment.
    Reference: Art.5 §3.1.3 — cmd_executor return type
    """
    status: str          # "COMPLETED" | "REJECTED"
    reason: Optional[str] = None


@dataclass
class CmdResult:
    """
    Result of executing a single command.
    Reference: Art.8 §2.3 — IF-WS-003 (COMMAND_ACK payload)
    """
    sequence_id: int
    status: str          # "EXECUTED" | "FAILED"
    executed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """
    A single entry in the hash-chained audit log.
    Reference: Art.8 §2.3 — IF-WS-006 (AUDIT_EVENT)
    Reference: Art.2 §3.5 — audit_events table schema

    Hash computation [REQ-FSW-LOG-SECURE]:
        hash = SHA256(prev_hash || timestamp || event_type || source || description)
    Where || denotes string concatenation.

    Fields:
        timestamp:   UTC timestamp of event
        event_type:  Machine-readable type (STATE_TRANSITION, WATCHDOG_RESTART, etc.)
        source:      Origin segment (FLIGHT, GROUND, TWIN, SCHEDULER)
        severity:    INFO, WARNING, or CRITICAL
        description: Human-readable description of the event
        metadata:    Additional structured data (JSON-serializable)
        hash:        SHA-256 hex digest of this entry
        prev_hash:   SHA-256 hex digest of the previous entry ("GENESIS" for first)
    """
    timestamp: datetime
    event_type: str
    source: str
    severity: Severity
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    hash: str = ""
    prev_hash: str = ""


@dataclass
class ChainVerificationResult:
    """
    Result of verifying the integrity of the hash-chained audit log.
    Reference: Art.8 §3.2 — IF-REST-004 (/api/events/verify response)
    """
    chain_valid: bool
    total_events: int
    break_at_index: Optional[int] = None
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None


# ---------------------------------------------------------------------------
# WebSocket Messages
# ---------------------------------------------------------------------------

@dataclass
class WsMessage:
    """
    Envelope for all WebSocket messages between Flight and Ground.
    Reference: Art.8 §2.2 — Message Envelope

    Every message on the WebSocket carries this envelope.
    The 'type' field determines how 'payload' is interpreted.

    Valid types (Art.8 §2.4):
        Flight → Ground: TELEMETRY, COMMAND_ACK, COMMAND_NACK,
                          AUDIT_EVENT, REPLAY_REQUEST
        Ground → Flight: PLAN_UPLOAD, TELEMETRY_ACK
    """
    type: str
    seq_id: int
    timestamp: datetime
    payload: Dict[str, Any]


# ---------------------------------------------------------------------------
# Digital Twin (used in Fase 4, defined here for completeness)
# ---------------------------------------------------------------------------

@dataclass
class Forecast:
    """
    A prediction generated by the Digital Twin.
    Reference: Art.8 §3.2 — IF-REST-005 (POST /api/twin/forecasts)
    """
    model_type: str               # "THERMAL" | "ENERGY"
    horizon_min: int              # Forecast horizon in minutes
    predicted_values: Dict[str, float]  # {minute_offset: predicted_value}
    breach_detected: bool = False
    breach_time: Optional[datetime] = None
    lead_time_min: Optional[float] = None
    rationale: Optional[str] = None
    alert_emitted: bool = False
