"""
Asterion One — Flight Software Core
=======================================
Main component: integrates ALL leaf components.
Reference: Phase 2, Art.3 (State Machine — complete specification)
Reference: Phase 2, Art.5 §3.1.1 — fsw_core

Implements the FDIR state machine with 4 states and 7 transitions:

  States:  BOOT → NOMINAL → SAFE → CRITICAL
  
  T1: BOOT → NOMINAL    (self-test pass)
  T2: BOOT → SAFE       (self-test fail)
  T3: NOMINAL → SAFE    (fault detected)
  T4: NOMINAL → NOMINAL (fault cleared before threshold)
  T5: SAFE → NOMINAL    (fault cleared + stability timer expired)
  T6: SAFE → CRITICAL   (consecutive WD restarts > MAX)
  T7: SAFE → SAFE       (fault still active, remain)

Main loop architecture [Art.3 §4]:
  1. Read sensors (sensor_sim)
  2. Evaluate faults (T3 guards)
  3. Execute pending commands (if NOMINAL)
  4. Send telemetry (comms_client — Phase 2)
  5. Notify watchdog (sd_notify)

Anti-oscillation [Art.3 §8]:
  - Hysteresis dead-band on recovery thresholds
  - Stability timer: conditions must be clear for N seconds before T5

Watchdog recovery [Art.3 §5]:
  - RECOVERY_MODE env var: if "SAFE", skip BOOT → start in SAFE
  - Boot counter tracking for escalation to CRITICAL (T6)

REQ-FSW-STATE-01: Explicit state machine (BOOT/NOMINAL/SAFE/CRITICAL)
REQ-FSW-WD-03s:   Recovery to SAFE in ≤3 seconds
"""

import os
import time
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable, List

from flight.models import FswState, Severity, TelemetryFrame
from flight.config import FswConfig
from flight.sensor_sim import SensorSim
from flight.audit_logger import AuditLogger
from flight.disk_queue import DiskQueue
from flight.cmd_executor import CmdExecutor
from flight.crypto_verifier import CryptoVerifier


class FswCore:
    """
    Flight Software Core — FDIR State Machine.

    Orchestrates all Flight Segment components in a tick-based
    main loop. Each tick: read sensors → evaluate → act → heartbeat.
    """

    # State codes for telemetry (matches sensor_sim convention)
    _STATE_CODES = {
        FswState.BOOT: 0,
        FswState.NOMINAL: 1,
        FswState.SAFE: 2,
        FswState.CRITICAL: 3,
    }

    def __init__(self, config: Optional[FswConfig] = None):
        """
        Initialize the FSW core with all sub-components.

        Args:
            config: Flight configuration. Uses defaults if None.
        """
        self._config = config or FswConfig()

        # --- Sub-components (leaf dependencies) ---
        self._sensors = SensorSim(config=self._config)
        self._audit = AuditLogger(
            log_path=self._config.AUDIT_LOG_PATH,
            source="FLIGHT",
        )
        self._queue = DiskQueue(
            queue_dir=self._config.QUEUE_DIR,
            max_depth=self._config.QUEUE_MAX_DEPTH,
        )
        self._crypto = CryptoVerifier(config=self._config)
        self._cmd_executor = CmdExecutor(
            crypto=self._crypto,
            audit=self._audit,
        )

        # --- State Machine ---
        self._state = FswState.BOOT
        self._prev_state: Optional[FswState] = None
        self._running = False
        self._tick_count = 0
        self._start_time = time.monotonic()

        # --- Watchdog tracking [Art.3 §5.3] ---
        self._consecutive_wd_restarts = 0
        self._boot_counter_path = "/tmp/asterion_boot_counter"

        # --- Anti-oscillation [Art.3 §8] ---
        self._stability_start: Optional[float] = None
        self._last_fault_time: Optional[float] = None

        # --- Telemetry sequence counter ---
        self._telem_seq_id = 0
        self._last_telem_time = 0.0

        # --- Callbacks for comms (set in Phase 2) ---
        self._on_telemetry: Optional[Callable] = None
        self._on_state_change: Optional[Callable] = None

        # --- Latest sensor snapshot ---
        self._last_sensors: Dict[str, Dict[str, float]] = {}

        # --- Fault details (for audit logging) ---
        self._active_faults: List[str] = []

    # -------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------

    @property
    def state(self) -> FswState:
        """Current FSW state."""
        return self._state

    @property
    def sensors(self) -> SensorSim:
        """Access to sensor simulator (for external updates)."""
        return self._sensors

    @property
    def audit(self) -> AuditLogger:
        """Access to audit logger."""
        return self._audit

    @property
    def cmd_executor(self) -> CmdExecutor:
        """Access to command executor."""
        return self._cmd_executor

    @property
    def queue(self) -> DiskQueue:
        """Access to disk queue."""
        return self._queue

    @property
    def config(self) -> FswConfig:
        """Access to configuration."""
        return self._config

    @property
    def consecutive_wd_restarts(self) -> int:
        """Number of consecutive watchdog restarts."""
        return self._consecutive_wd_restarts

    @property
    def tick_count(self) -> int:
        """Number of main loop ticks executed."""
        return self._tick_count

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the FSW main loop.

        Checks RECOVERY_MODE env var:
          - "SAFE" → skip BOOT, enter SAFE directly (WD restart)
          - anything else → normal BOOT sequence
        """
        recovery_mode = os.environ.get("RECOVERY_MODE", "")

        if recovery_mode == "SAFE":
            # Watchdog restart path [Art.3 §5.1]
            self._consecutive_wd_restarts = self._load_boot_counter() + 1
            self._save_boot_counter(self._consecutive_wd_restarts)

            # Check escalation [Art.3 §5.3 — T6]
            if self._consecutive_wd_restarts > self._config.MAX_WD_RESTARTS:
                self._transition_to(FswState.CRITICAL,
                                    "Watchdog escalation: "
                                    f"{self._consecutive_wd_restarts} "
                                    f"consecutive restarts > "
                                    f"{self._config.MAX_WD_RESTARTS}")
                self._running = False
                return
            else:
                self._transition_to(FswState.SAFE,
                                    f"Watchdog recovery (restart "
                                    f"#{self._consecutive_wd_restarts})")
                self._sensors.update_wd_restarts(
                    self._consecutive_wd_restarts)
        else:
            # Normal boot
            self._save_boot_counter(0)
            self._consecutive_wd_restarts = 0
            self._transition_to(FswState.BOOT, "System boot initiated")

        self._running = True
        self._notify_watchdog_ready()

    def stop(self) -> None:
        """Stop the main loop."""
        self._running = False

    def tick(self) -> FswState:
        """
        Execute one main loop iteration.

        Returns the current state after this tick.
        Call this in a loop or from a scheduler.

        Reference: Art.3 §4 — Main Loop Architecture
        """
        self._tick_count += 1

        # Dispatch based on current state
        if self._state == FswState.BOOT:
            self._do_boot()
        elif self._state == FswState.NOMINAL:
            self._do_nominal()
        elif self._state == FswState.SAFE:
            self._do_safe()
        elif self._state == FswState.CRITICAL:
            self._do_critical()

        # Update sensor meta-telemetry
        self._sensors.update_fsw_state(
            self._STATE_CODES.get(self._state, 0)
        )

        # Notify watchdog (if not CRITICAL)
        if self._state != FswState.CRITICAL:
            self._notify_watchdog()

        return self._state

    def run_loop(self) -> None:
        """
        Run the main loop continuously until stop() is called.
        Blocks the calling thread.
        """
        self.start()
        while self._running:
            self.tick()
            time.sleep(self._config.TICK_INTERVAL_SEC)

    # -------------------------------------------------------------------
    # State Handlers [Art.3 §4]
    # -------------------------------------------------------------------

    def _do_boot(self) -> None:
        """
        BOOT state handler.

        Runs self-test. On success → NOMINAL (T1). On failure → SAFE (T2).
        """
        test_passed = self._run_self_test()

        if test_passed:
            # T1: BOOT → NOMINAL
            self._transition_to(FswState.NOMINAL,
                                "Self-test passed, entering NOMINAL")
            # Clear boot counter on clean start
            self._save_boot_counter(0)
            self._consecutive_wd_restarts = 0
        else:
            # T2: BOOT → SAFE
            self._transition_to(FswState.SAFE,
                                "Self-test failed, entering SAFE")

    def _do_nominal(self) -> None:
        """
        NOMINAL state handler — full operations.

        1. Read sensors
        2. Evaluate fault conditions (T3 guards)
        3. Execute pending commands
        4. Generate telemetry
        """
        # 1. Read sensors
        self._last_sensors = self._sensors.read_all()

        # 2. Evaluate faults [Art.3 §4, T3 guards]
        faults = self._evaluate_faults(self._last_sensors)

        if faults:
            # T3: NOMINAL → SAFE
            self._active_faults = faults
            self._transition_to(
                FswState.SAFE,
                f"Fault detected: {'; '.join(faults)}",
            )
            # Queue pending commands to disk [Art.3 §4, T3 actions]
            return

        # 3. Generate and emit telemetry
        self._emit_telemetry(self._last_sensors)

    def _do_safe(self) -> None:
        """
        SAFE state handler — reduced operations.

        1. Read sensors (reduced rate)
        2. Evaluate recovery conditions (T5 guards + stability)
        3. Check escalation (T6)
        4. Reduced telemetry
        """
        # Reduced telemetry rate
        now = time.monotonic()
        if now - self._last_telem_time < self._config.TELEMETRY_RATE_SAFE_SEC:
            return  # Skip this tick (rate limiting)

        # 1. Read sensors
        self._last_sensors = self._sensors.read_all()

        # 2. Check escalation first [Art.3 §5.3 — T6]
        if self._consecutive_wd_restarts > self._config.MAX_WD_RESTARTS:
            self._transition_to(
                FswState.CRITICAL,
                f"Escalation: {self._consecutive_wd_restarts} "
                f"WD restarts > {self._config.MAX_WD_RESTARTS}",
            )
            return

        # 3. Evaluate recovery [Art.3 §8 — T5 guards]
        recovery_ok = self._evaluate_recovery(self._last_sensors)

        if recovery_ok:
            # T5: SAFE → NOMINAL
            self._active_faults.clear()
            self._stability_start = None
            self._transition_to(
                FswState.NOMINAL,
                "All faults cleared, stability timer expired",
            )
            # Reset boot counter on successful recovery
            self._save_boot_counter(0)
            self._consecutive_wd_restarts = 0
            return

        # 4. Emit reduced telemetry
        self._emit_telemetry(self._last_sensors)

    def _do_critical(self) -> None:
        """
        CRITICAL state handler — ceased operations.

        Logs final state and stops. No recovery from CRITICAL
        without manual restart (power cycle).
        """
        if self._running:
            self._audit.log(
                event_type="CRITICAL_HALT",
                severity=Severity.CRITICAL,
                description="FSW in CRITICAL state — operations ceased",
                metadata={
                    "wd_restarts": self._consecutive_wd_restarts,
                    "uptime_s": time.monotonic() - self._start_time,
                },
            )
            self._running = False

    # -------------------------------------------------------------------
    # Fault Evaluation [Art.3 §4, T3 guards]
    # -------------------------------------------------------------------

    def _evaluate_faults(
        self, sensors: Dict[str, Dict[str, float]]
    ) -> List[str]:
        """
        Evaluate T3 fault conditions against sensor data.

        Returns list of fault descriptions (empty = no faults).
        Any single fault triggers T3 (NOMINAL → SAFE).

        Guards [Art.3 §4]:
          cpu_temp_c   > THRESHOLD_TEMP_WARN_C
          voltage_v    < VOLTAGE_MIN_V
          battery_soc  < BATTERY_SOC_MIN
          error_rate   > COMMS_ERROR_RATE_MAX
        """
        cfg = self._config
        faults = []

        thermal = sensors.get("THERMAL", {})
        power = sensors.get("POWER", {})
        comms = sensors.get("COMMS", {})

        cpu_temp = thermal.get("cpu_temp_c", 0)
        if cpu_temp > cfg.THRESHOLD_TEMP_WARN_C:
            faults.append(
                f"cpu_temp={cpu_temp:.1f}°C > "
                f"threshold={cfg.THRESHOLD_TEMP_WARN_C}°C"
            )

        voltage = power.get("voltage_v", cfg.SENSOR_NOMINAL_VOLTAGE_V)
        if voltage < cfg.VOLTAGE_MIN_V:
            faults.append(
                f"voltage={voltage:.2f}V < "
                f"min={cfg.VOLTAGE_MIN_V}V"
            )

        soc = power.get("battery_soc", 1.0)
        if soc < cfg.BATTERY_SOC_MIN:
            faults.append(
                f"battery_soc={soc:.2f} < "
                f"min={cfg.BATTERY_SOC_MIN}"
            )

        error_rate = comms.get("error_rate", 0)
        if error_rate > cfg.COMMS_ERROR_RATE_MAX:
            faults.append(
                f"error_rate={error_rate:.3f} > "
                f"max={cfg.COMMS_ERROR_RATE_MAX}"
            )

        return faults

    # -------------------------------------------------------------------
    # Recovery Evaluation [Art.3 §8 — T5 guards]
    # -------------------------------------------------------------------

    def _evaluate_recovery(
        self, sensors: Dict[str, Dict[str, float]]
    ) -> bool:
        """
        Evaluate T5 recovery conditions with hysteresis + stability timer.

        Recovery requires:
          1. ALL fault conditions cleared (with hysteresis dead-band)
          2. Conditions remain clear for STABILITY_TIMER_SEC continuous seconds

        Hysteresis [Art.3 §8]:
          cpu_temp < (THRESHOLD_TEMP_WARN_C - HYSTERESIS_TEMP_C)
          voltage  > (VOLTAGE_MIN_V + 0.1)  [small dead-band]
          battery  > (BATTERY_SOC_MIN + 0.05)
          error_rate < (COMMS_ERROR_RATE_MAX - 0.02)
        """
        cfg = self._config
        thermal = sensors.get("THERMAL", {})
        power = sensors.get("POWER", {})
        comms = sensors.get("COMMS", {})

        # Check with hysteresis
        conditions_clear = True

        cpu_temp = thermal.get("cpu_temp_c", 0)
        recovery_temp = cfg.THRESHOLD_TEMP_WARN_C - cfg.HYSTERESIS_TEMP_C
        if cpu_temp >= recovery_temp:
            conditions_clear = False

        voltage = power.get("voltage_v", cfg.SENSOR_NOMINAL_VOLTAGE_V)
        if voltage <= cfg.VOLTAGE_MIN_V + 0.1:
            conditions_clear = False

        soc = power.get("battery_soc", 1.0)
        if soc <= cfg.BATTERY_SOC_MIN + 0.05:
            conditions_clear = False

        error_rate = comms.get("error_rate", 0)
        if error_rate >= cfg.COMMS_ERROR_RATE_MAX - 0.02:
            conditions_clear = False

        # Stability timer logic
        now = time.monotonic()

        if not conditions_clear:
            # Reset stability timer
            self._stability_start = None
            return False

        if self._stability_start is None:
            # Start the timer
            self._stability_start = now
            return False

        elapsed = now - self._stability_start
        if elapsed >= cfg.STABILITY_TIMER_SEC:
            return True  # Stable long enough → T5 fires

        return False  # Still waiting for stability

    # -------------------------------------------------------------------
    # State Transitions
    # -------------------------------------------------------------------

    def _transition_to(self, new_state: FswState, reason: str) -> None:
        """
        Execute a state transition with full audit logging.

        Args:
            new_state: Target state.
            reason: Human-readable reason for the transition.
        """
        old_state = self._state
        self._prev_state = old_state
        self._state = new_state

        # Determine transition code
        transition_map = {
            (FswState.BOOT, FswState.NOMINAL): "T1",
            (FswState.BOOT, FswState.SAFE): "T2",
            (FswState.NOMINAL, FswState.SAFE): "T3",
            (FswState.SAFE, FswState.NOMINAL): "T5",
            (FswState.SAFE, FswState.CRITICAL): "T6",
        }
        t_code = transition_map.get((old_state, new_state), "T?")

        # Determine severity
        if new_state in (FswState.SAFE, FswState.CRITICAL):
            severity = Severity.WARNING if new_state == FswState.SAFE \
                else Severity.CRITICAL
        else:
            severity = Severity.INFO

        self._audit.log(
            event_type="STATE_TRANSITION",
            severity=severity,
            description=f"{t_code}: {old_state.value} → {new_state.value}: {reason}",
            metadata={
                "transition": t_code,
                "from_state": old_state.value,
                "to_state": new_state.value,
                "reason": reason,
                "wd_restarts": self._consecutive_wd_restarts,
            },
        )

        # Notify callback (for comms — Phase 2)
        if self._on_state_change:
            self._on_state_change(old_state, new_state)

    # -------------------------------------------------------------------
    # Self-Test [Art.3 §4, BOOT handler]
    # -------------------------------------------------------------------

    def _run_self_test(self) -> bool:
        """
        Run BOOT self-test.

        Checks:
          1. All 5 sensor subsystems respond
          2. Audit logger can write
          3. Disk queue directory accessible

        Returns True if all checks pass.
        """
        try:
            # Test 1: Sensors respond
            data = self._sensors.read_all()
            if len(data) != 5:
                return False

            # Test 2: Audit logger works
            self._audit.log(
                event_type="SELF_TEST",
                severity=Severity.INFO,
                description="BOOT self-test: starting checks",
            )

            # Test 3: Disk queue accessible
            _ = self._queue.depth()

            return True

        except Exception:
            return False

    # -------------------------------------------------------------------
    # Telemetry Generation
    # -------------------------------------------------------------------

    def _emit_telemetry(
        self, sensors: Dict[str, Dict[str, float]]
    ) -> None:
        """Generate and emit a telemetry frame."""
        self._telem_seq_id += 1
        self._last_telem_time = time.monotonic()

        frame = TelemetryFrame(
            seq_id=self._telem_seq_id,
            timestamp=datetime.now(timezone.utc),
            fsw_state=self._state,
            subsystems=sensors,
        )

        # Callback for comms_client (Phase 2)
        if self._on_telemetry:
            self._on_telemetry(frame)

    # -------------------------------------------------------------------
    # Watchdog Interface [Art.8 §5 — IF-SYS-001]
    # -------------------------------------------------------------------

    def _notify_watchdog(self) -> None:
        """Send heartbeat to Systemd watchdog."""
        try:
            import sdnotify
            n = sdnotify.SystemdNotifier()
            n.notify("WATCHDOG=1")
        except ImportError:
            pass  # Not running under Systemd (dev/test mode)

    def _notify_watchdog_ready(self) -> None:
        """Signal to Systemd that the service is ready."""
        try:
            import sdnotify
            n = sdnotify.SystemdNotifier()
            n.notify("READY=1")
        except ImportError:
            pass

    # -------------------------------------------------------------------
    # Boot Counter Persistence [Art.3 §5.3]
    # -------------------------------------------------------------------

    def _load_boot_counter(self) -> int:
        """Load the persistent boot counter (for WD escalation)."""
        try:
            with open(self._boot_counter_path, "r") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return 0

    def _save_boot_counter(self, count: int) -> None:
        """Save the boot counter to disk."""
        try:
            with open(self._boot_counter_path, "w") as f:
                f.write(str(count))
        except OSError:
            pass

    # -------------------------------------------------------------------
    # Callback Registration (Phase 2 integration)
    # -------------------------------------------------------------------

    def set_telemetry_callback(self, callback: Callable) -> None:
        """Register callback for telemetry frames."""
        self._on_telemetry = callback

    def set_state_change_callback(self, callback: Callable) -> None:
        """Register callback for state transitions."""
        self._on_state_change = callback
