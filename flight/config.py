"""
Asterion One — Flight Segment Configuration
=============================================
All configurable parameters for the Flight Software.
Reference: Phase 2, Artifact 3 §11 — Configurable Parameters

Every threshold, timer, and limit used by fsw_core, sensor_sim,
and other Flight components is defined here. This enables:
1. Tuning for different hardware (RPi 4 vs RPi 5)
2. Adjusting for demo scenarios (shorter timers)
3. Unit testing with custom configurations

All values have sensible defaults for Raspberry Pi 4 hardware.
Override via environment variables or config file.
"""

import os
from dataclasses import dataclass


@dataclass
class FswConfig:
    """Master configuration for the Flight Software."""

    # -----------------------------------------------------------------------
    # State Machine — Tick Interval
    # Reference: Art.3 §4 — main_loop tick
    # -----------------------------------------------------------------------
    TICK_INTERVAL_SEC: float = 1.0
    """Main loop tick interval in seconds. Determines sensor read frequency
    in NOMINAL mode and watchdog heartbeat frequency."""

    # -----------------------------------------------------------------------
    # Fault Detection — Thermal Thresholds
    # Reference: Art.3 §4, T3 guards
    # -----------------------------------------------------------------------
    THRESHOLD_TEMP_WARN_C: float = 75.0
    """CPU temperature (°C) above which T3 (NOMINAL→SAFE) triggers.
    Based on Raspberry Pi 4 throttling temperature (~80°C) with margin."""

    THRESHOLD_TEMP_CRIT_C: float = 85.0
    """CPU temperature (°C) above which severity escalates to CRITICAL
    in audit logging. FSW enters SAFE at WARN, not CRIT."""

    HYSTERESIS_TEMP_C: float = 5.0
    """Temperature hysteresis dead band (°C). Recovery (T5) requires
    temp < (THRESHOLD_TEMP_WARN_C - HYSTERESIS_TEMP_C) = 70°C.
    Prevents oscillation between NOMINAL and SAFE.
    Reference: Art.3 §8 — Anti-Oscillation Mechanisms."""

    # -----------------------------------------------------------------------
    # Fault Detection — Power Thresholds
    # Reference: Art.3 §4, T3 guards
    # -----------------------------------------------------------------------
    VOLTAGE_MIN_V: float = 4.6
    """Minimum voltage (V) below which T3 triggers.
    Raspberry Pi 4 nominal is 5.1V; 4.6V indicates under-voltage."""

    BATTERY_SOC_MIN: float = 0.10
    """Minimum battery state-of-charge (0.0-1.0) below which T3 triggers."""

    # -----------------------------------------------------------------------
    # Fault Detection — Communications Thresholds
    # Reference: Art.3 §4, T3 guards
    # -----------------------------------------------------------------------
    COMMS_ERROR_RATE_MAX: float = 0.10
    """Maximum acceptable communication error rate (0.0-1.0).
    Above this, T3 triggers."""

    # -----------------------------------------------------------------------
    # Recovery — Stability Timer
    # Reference: Art.3 §8 — Anti-Oscillation: Stability Timer
    # -----------------------------------------------------------------------
    STABILITY_TIMER_SEC: float = 30.0
    """Duration (seconds) that all fault conditions must remain cleared
    before T5 (SAFE→NOMINAL) executes. Prevents premature recovery
    if sensor readings fluctuate near threshold boundaries."""

    # -----------------------------------------------------------------------
    # Watchdog Configuration
    # Reference: Art.3 §5 — Watchdog Architecture
    # -----------------------------------------------------------------------
    WD_HEARTBEAT_INTERVAL_SEC: float = 1.0
    """Interval (seconds) between sd_notify("WATCHDOG=1") calls.
    Must be significantly less than WD_TIMEOUT_SEC to prevent
    false triggers. Rule of thumb: HEARTBEAT = TIMEOUT / 3."""

    WD_TIMEOUT_SEC: float = 3.0
    """Systemd WatchdogSec value (seconds). If no heartbeat received
    within this window, Systemd kills and restarts the process.
    [REQ-FSW-WD-03s] — this IS the 3-second budget."""

    MAX_WD_RESTARTS: int = 3
    """Maximum consecutive watchdog restarts before escalation to
    CRITICAL (T6: SAFE→CRITICAL). Prevents infinite restart loops.
    Reference: Art.3 §5.3 — Watchdog Escalation Policy."""

    # -----------------------------------------------------------------------
    # BOOT Self-Test Configuration
    # Reference: Art.3 §4, T1/T2 guards
    # -----------------------------------------------------------------------
    BOOT_SELF_TEST_TIMEOUT_SEC: float = 5.0
    """Maximum time (seconds) allowed for the BOOT self-test.
    If self-test doesn't complete within this window, T2 triggers
    (BOOT→SAFE) as a precaution."""

    # -----------------------------------------------------------------------
    # Telemetry Rates
    # Reference: Art.3 §6 — Functional Matrix
    # -----------------------------------------------------------------------
    TELEMETRY_RATE_NOMINAL_SEC: float = 1.0
    """Telemetry frame generation interval in NOMINAL mode (seconds)."""

    TELEMETRY_RATE_SAFE_SEC: float = 10.0
    """Telemetry frame generation interval in SAFE mode (seconds).
    Reduced to conserve resources."""

    # -----------------------------------------------------------------------
    # Communications
    # Reference: Art.8 §2.1 — IF-WS-CONN
    # -----------------------------------------------------------------------
    GROUND_WS_URL: str = "ws://192.168.1.100:8081/flight"
    """WebSocket URL of the Ground Segment ws_gateway.
    Flight connects as CLIENT to this URL."""

    WS_RECONNECT_INTERVAL_SEC: float = 5.0
    """Interval (seconds) between reconnection attempts when
    the WebSocket link is down."""

    WS_PING_INTERVAL_SEC: float = 30.0
    """WebSocket transport-level ping/pong interval (seconds)."""

    # -----------------------------------------------------------------------
    # Disk Queue
    # Reference: Art.5 §3.1.7 — disk_queue
    # -----------------------------------------------------------------------
    QUEUE_DIR: str = "/var/lib/asterion/queue"
    """Directory for on-disk message queue files.
    Each message stored as {seq_id:06d}.json."""

    QUEUE_MAX_DEPTH: int = 10000
    """Maximum number of messages in the disk queue before
    oldest messages are dropped (overflow protection)."""

    # -----------------------------------------------------------------------
    # Audit Logger
    # Reference: Art.5 §3.1.6 — audit_logger
    # -----------------------------------------------------------------------
    AUDIT_LOG_PATH: str = "/var/log/asterion/audit.jsonl"
    """Path to the hash-chained audit log file (JSONL format)."""

    # -----------------------------------------------------------------------
    # Crypto
    # Reference: Art.5 §3.1.4 — crypto_verifier
    # -----------------------------------------------------------------------
    TRUSTED_KEYS_PATH: str = "/etc/asterion/trusted_keys.json"
    """Path to JSON file containing trusted Ed25519 public keys.
    Format: [{"name": "operator1", "public_key": "base64..."}]"""

    # -----------------------------------------------------------------------
    # Sensor Simulator
    # Reference: Art.5 §3.1.5 — sensor_sim
    # -----------------------------------------------------------------------
    SENSOR_USE_REAL_TEMP: bool = False
    """If True, read real CPU temperature from Raspberry Pi hardware
    (vcgencmd measure_temp). If False, use synthetic data only."""

    SENSOR_NOMINAL_TEMP_C: float = 55.0
    """Baseline synthetic CPU temperature (°C) in nominal conditions."""

    SENSOR_NOMINAL_VOLTAGE_V: float = 5.1
    """Baseline synthetic voltage (V) in nominal conditions."""

    SENSOR_NOMINAL_POWER_W: float = 4.0
    """Baseline synthetic power draw (W) in nominal conditions."""

    SENSOR_NOISE_AMPLITUDE: float = 2.0
    """Amplitude of random noise added to synthetic sensor readings.
    Simulates real-world sensor jitter."""

    @classmethod
    def from_env(cls) -> "FswConfig":
        """
        Create a config instance with values overridden by environment
        variables where present.
        
        Environment variable naming convention:
            ASTERION_{FIELD_NAME}
        
        Example:
            ASTERION_THRESHOLD_TEMP_WARN_C=80.0
            ASTERION_GROUND_WS_URL=ws://localhost:8081/flight
            ASTERION_WD_TIMEOUT_SEC=5.0
        """
        config = cls()
        prefix = "ASTERION_"

        for field_name in config.__dataclass_fields__:
            env_key = prefix + field_name
            env_val = os.environ.get(env_key)

            if env_val is not None:
                field_type = type(getattr(config, field_name))
                try:
                    if field_type == bool:
                        # Handle bool specially: "true"/"1" → True
                        setattr(config, field_name, env_val.lower() in ("true", "1", "yes"))
                    elif field_type == int:
                        setattr(config, field_name, int(env_val))
                    elif field_type == float:
                        setattr(config, field_name, float(env_val))
                    else:
                        setattr(config, field_name, env_val)
                except (ValueError, TypeError):
                    pass  # Keep default if env var is malformed

        return config
