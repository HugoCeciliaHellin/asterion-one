"""
Asterion One — Flight Segment Smoke Test
==========================================
Verifies that all models and config load without import errors.
This is the baseline test — Phase 1 will add real unit tests.
"""


def test_models_import():
    """Verify that all data models are importable."""
    from flight.models import (
        FswState,
        Severity,
        CommandStatus,
        PlanStatus,
        WindowStatus,
        TelemetryFrame,
        Command,
        CommandPlan,
        PlanResult,
        CmdResult,
        AuditEntry,
        ChainVerificationResult,
        WsMessage,
        Forecast,
    )
    # Verify enum values exist
    assert FswState.BOOT == "BOOT"
    assert FswState.NOMINAL == "NOMINAL"
    assert FswState.SAFE == "SAFE"
    assert FswState.CRITICAL == "CRITICAL"

    assert Severity.INFO == "INFO"
    assert Severity.WARNING == "WARNING"
    assert Severity.CRITICAL == "CRITICAL"


def test_config_import():
    """Verify that config loads with default values."""
    from flight.config import FswConfig

    config = FswConfig()
    assert config.THRESHOLD_TEMP_WARN_C == 75.0
    assert config.WD_TIMEOUT_SEC == 3.0
    assert config.MAX_WD_RESTARTS == 3
    assert config.STABILITY_TIMER_SEC == 30.0
    assert config.TELEMETRY_RATE_NOMINAL_SEC == 1.0
    assert config.TELEMETRY_RATE_SAFE_SEC == 10.0


def test_config_from_env():
    """Verify that config reads from environment variables."""
    import os
    from flight.config import FswConfig

    # Set env vars
    env_vars = {
        "ASTERION_THRESHOLD_TEMP_WARN_C": "80.0",
        "ASTERION_WD_TIMEOUT_SEC": "5.0",
        "ASTERION_MAX_WD_RESTARTS": "5",
        "ASTERION_SENSOR_USE_REAL_TEMP": "true",
    }
    old_values = {}
    for k, v in env_vars.items():
        old_values[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        config = FswConfig.from_env()
        assert config.THRESHOLD_TEMP_WARN_C == 80.0
        assert config.WD_TIMEOUT_SEC == 5.0
        assert config.MAX_WD_RESTARTS == 5
        assert config.SENSOR_USE_REAL_TEMP is True
    finally:
        # Restore env
        for k, old_v in old_values.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


def test_fsw_state_transitions():
    """Verify FswState enum string representation."""
    from flight.models import FswState

    # String enum allows direct comparison with JSON strings
    assert FswState("NOMINAL") == FswState.NOMINAL
    assert str(FswState.SAFE) == "FswState.SAFE"
    assert FswState.CRITICAL.value == "CRITICAL"


def test_telemetry_frame_creation():
    """Verify TelemetryFrame can be instantiated with subsystem data."""
    from datetime import datetime, timezone
    from flight.models import TelemetryFrame, FswState

    frame = TelemetryFrame(
        seq_id=1,
        timestamp=datetime.now(timezone.utc),
        fsw_state=FswState.NOMINAL,
        subsystems={
            "THERMAL": {"cpu_temp_c": 55.0, "board_temp_c": 40.0},
            "POWER": {"voltage_v": 5.1, "current_ma": 800},
            "CPU": {"cpu_usage_pct": 45.0},
            "COMMS": {"ws_connected": 1.0, "msg_queue_depth": 0},
            "FSW": {"state": 1.0, "uptime_s": 3600},
        },
    )
    assert frame.seq_id == 1
    assert frame.fsw_state == FswState.NOMINAL
    assert frame.subsystems["THERMAL"]["cpu_temp_c"] == 55.0
    assert len(frame.subsystems) == 5


def test_audit_entry_creation():
    """Verify AuditEntry with hash chain fields."""
    from datetime import datetime, timezone
    from flight.models import AuditEntry, Severity

    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        event_type="STATE_TRANSITION",
        source="FLIGHT",
        severity=Severity.WARNING,
        description="NOMINAL → SAFE: cpu_temp threshold exceeded",
        metadata={"cpu_temp_c": 78.2, "threshold_c": 75.0},
        hash="abc123",
        prev_hash="GENESIS",
    )
    assert entry.event_type == "STATE_TRANSITION"
    assert entry.severity == Severity.WARNING
    assert entry.prev_hash == "GENESIS"
    assert entry.metadata["cpu_temp_c"] == 78.2
