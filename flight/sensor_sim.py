"""
Asterion One — Sensor Simulator
=================================
Leaf component: no internal dependencies.
Reference: Phase 2, Art.5 §3.1.5 — sensor_sim

Generates synthetic telemetry data for 5 subsystems:
  THERMAL  → cpu_temp_c, board_temp_c
  POWER    → voltage_v, current_ma, battery_soc, power_w
  CPU      → cpu_usage_pct, memory_usage_pct
  COMMS    → ws_connected, msg_queue_depth, error_rate
  FSW      → state_code, uptime_s, wd_restarts

Design decisions:
  - Synthetic data with configurable noise (Gaussian jitter)
  - Override mode for fault injection (set_override / clear_override)
  - Optional real CPU temperature on Raspberry Pi (vcgencmd)
  - Thread-safe: overrides are applied atomically per read

Interface contract (ISensorData from Art.8 §4):
  read_all()              → Dict[str, Dict[str, float]]
  read_subsystem(name)    → Dict[str, float]
  set_override(subsystem, values)   → None
  clear_override(subsystem)         → None
  clear_all_overrides()             → None
"""

import random
import subprocess
import time
import threading
from typing import Dict, Optional

from flight.config import FswConfig


class SensorSim:
    """
    Simulates satellite sensor subsystems with synthetic data.

    Supports two modes:
      1. Normal: generates realistic noisy readings around baseline values
      2. Override: fault_injector sets specific values for testing

    Override takes precedence — when active for a subsystem,
    specified metrics come from the override dict, others keep
    synthetic values (merge semantics).
    """

    # Subsystem names — canonical set referenced throughout the system
    SUBSYSTEM_NAMES = ("THERMAL", "POWER", "CPU", "COMMS", "FSW")

    def __init__(self, config: Optional[FswConfig] = None):
        """
        Initialize the sensor simulator.

        Args:
            config: Flight configuration. Uses defaults if None.
        """
        self._config = config or FswConfig()
        self._start_time = time.monotonic()
        self._lock = threading.Lock()

        # Override storage: subsystem_name → {metric: value}
        self._overrides: Dict[str, Dict[str, float]] = {}

        # Internal state for realistic simulation
        self._battery_soc = 0.85  # Start at 85% charge
        self._ws_connected = False
        self._msg_queue_depth = 0
        self._wd_restarts = 0
        self._fsw_state_code = 0  # 0=BOOT, 1=NOMINAL, 2=SAFE, 3=CRITICAL

    # -------------------------------------------------------------------
    # Public Interface — ISensorData
    # -------------------------------------------------------------------

    def read_all(self) -> Dict[str, Dict[str, float]]:
        """
        Read all 5 subsystems in a single atomic snapshot.

        Returns:
            Dict mapping subsystem name → metrics dict.
            Example: {"THERMAL": {"cpu_temp_c": 55.2, ...}, ...}

        Reference: Art.8 §2.3 IF-WS-001 — telemetry.subsystems
        """
        with self._lock:
            return {name: self._read_subsystem_locked(name)
                    for name in self.SUBSYSTEM_NAMES}

    def read_subsystem(self, name: str) -> Dict[str, float]:
        """
        Read a single subsystem.

        Args:
            name: One of THERMAL, POWER, CPU, COMMS, FSW

        Returns:
            Dict of metric_name → float value

        Raises:
            ValueError: if name is not a valid subsystem
        """
        if name not in self.SUBSYSTEM_NAMES:
            raise ValueError(
                f"Unknown subsystem '{name}'. "
                f"Valid: {self.SUBSYSTEM_NAMES}"
            )
        with self._lock:
            return self._read_subsystem_locked(name)

    def set_override(self, subsystem: str, values: Dict[str, float]) -> None:
        """
        Set override values for a subsystem (used by fault_injector).

        When active, specified metrics use the override value;
        unspecified metrics keep their synthetic readings (merge).

        Args:
            subsystem: Subsystem name (THERMAL, POWER, CPU, COMMS, FSW)
            values: Dict of metric_name → override_value
                    Example: {"cpu_temp_c": 85.0}

        Reference: Art.5 §3.4.2 — fault_injector → sensor_sim override
        """
        if subsystem not in self.SUBSYSTEM_NAMES:
            raise ValueError(
                f"Unknown subsystem '{subsystem}'. "
                f"Valid: {self.SUBSYSTEM_NAMES}"
            )
        with self._lock:
            self._overrides[subsystem] = dict(values)

    def clear_override(self, subsystem: str) -> None:
        """Remove override for a specific subsystem."""
        with self._lock:
            self._overrides.pop(subsystem, None)

    def clear_all_overrides(self) -> None:
        """Remove all overrides — return to normal synthetic data."""
        with self._lock:
            self._overrides.clear()

    # -------------------------------------------------------------------
    # External State Updates (called by fsw_core, comms_client)
    # -------------------------------------------------------------------

    def update_fsw_state(self, state_code: int) -> None:
        """Update the FSW state code reported in telemetry.
        0=BOOT, 1=NOMINAL, 2=SAFE, 3=CRITICAL."""
        with self._lock:
            self._fsw_state_code = state_code

    def update_comms_status(self, connected: bool, queue_depth: int) -> None:
        """Update communication status for COMMS subsystem telemetry."""
        with self._lock:
            self._ws_connected = connected
            self._msg_queue_depth = queue_depth

    def update_wd_restarts(self, count: int) -> None:
        """Update watchdog restart count for FSW subsystem telemetry."""
        with self._lock:
            self._wd_restarts = count

    def update_battery_soc(self, soc: float) -> None:
        """Update battery state of charge (0.0-1.0)."""
        with self._lock:
            self._battery_soc = max(0.0, min(1.0, soc))

    # -------------------------------------------------------------------
    # Internal — Subsystem Readers (must hold self._lock)
    # -------------------------------------------------------------------

    def _read_subsystem_locked(self, name: str) -> Dict[str, float]:
        """Read a subsystem, applying overrides where present."""
        # Generate normal synthetic readings
        normal = self._generate_normal(name)

        # Apply overrides: override values replace matching normal values
        override = self._overrides.get(name)
        if override:
            merged = dict(normal)
            merged.update(override)
            return merged

        return normal

    def _generate_normal(self, name: str) -> Dict[str, float]:
        """Generate normal synthetic readings for a subsystem."""
        if name == "THERMAL":
            return self._gen_thermal()
        elif name == "POWER":
            return self._gen_power()
        elif name == "CPU":
            return self._gen_cpu()
        elif name == "COMMS":
            return self._gen_comms()
        elif name == "FSW":
            return self._gen_fsw()
        else:
            return {}

    def _gen_thermal(self) -> Dict[str, float]:
        """
        THERMAL subsystem readings.

        cpu_temp_c:   CPU core temperature (C).
                      Real on RPi (vcgencmd), synthetic otherwise.
                      T3 guard: cpu_temp_c > THRESHOLD_TEMP_WARN_C
        board_temp_c: Board/ambient temperature (C).
                      Always synthetic.
        """
        cfg = self._config
        noise = cfg.SENSOR_NOISE_AMPLITUDE

        if cfg.SENSOR_USE_REAL_TEMP:
            cpu_temp = self._read_rpi_cpu_temp()
        else:
            cpu_temp = cfg.SENSOR_NOMINAL_TEMP_C + random.gauss(0, noise)

        board_temp = cpu_temp - 15.0 + random.gauss(0, noise * 0.5)

        return {
            "cpu_temp_c": round(cpu_temp, 2),
            "board_temp_c": round(board_temp, 2),
        }

    def _gen_power(self) -> Dict[str, float]:
        """
        POWER subsystem readings.

        voltage_v:    Supply voltage (V). Nominal: 5.1V (RPi 4).
                      T3 guard: voltage_v < VOLTAGE_MIN_V
        current_ma:   Current draw (mA). Varies with CPU load.
        battery_soc:  State of charge (0.0-1.0). Drains slowly.
                      T3 guard: battery_soc < BATTERY_SOC_MIN
        power_w:      Instantaneous power draw (W).
        """
        cfg = self._config
        noise = cfg.SENSOR_NOISE_AMPLITUDE

        voltage = cfg.SENSOR_NOMINAL_VOLTAGE_V + random.gauss(0, noise * 0.02)
        current = 600 + random.gauss(0, 50)
        power = cfg.SENSOR_NOMINAL_POWER_W + random.gauss(0, noise * 0.1)

        # Battery slowly drains (simulates orbital power cycle)
        self._battery_soc = max(0.0, self._battery_soc - 0.00001)

        return {
            "voltage_v": round(voltage, 3),
            "current_ma": round(max(0, current), 1),
            "battery_soc": round(self._battery_soc, 4),
            "power_w": round(max(0, power), 2),
        }

    def _gen_cpu(self) -> Dict[str, float]:
        """
        CPU subsystem readings.

        cpu_usage_pct:    CPU utilization (%).
        memory_usage_pct: Memory utilization (%).
        """
        noise = self._config.SENSOR_NOISE_AMPLITUDE

        cpu = 35.0 + random.gauss(0, noise * 2)
        mem = 40.0 + random.gauss(0, noise * 1.5)

        return {
            "cpu_usage_pct": round(max(0, min(100, cpu)), 1),
            "memory_usage_pct": round(max(0, min(100, mem)), 1),
        }

    def _gen_comms(self) -> Dict[str, float]:
        """
        COMMS subsystem readings.

        ws_connected:    1.0 if WebSocket link is open, 0.0 otherwise.
        msg_queue_depth: Number of messages in disk_queue.
        error_rate:      Fraction of failed transmissions (0.0-1.0).
                         T3 guard: error_rate > COMMS_ERROR_RATE_MAX
        """
        error_rate = abs(random.gauss(0, 0.005))

        return {
            "ws_connected": 1.0 if self._ws_connected else 0.0,
            "msg_queue_depth": float(self._msg_queue_depth),
            "error_rate": round(min(1.0, error_rate), 4),
        }

    def _gen_fsw(self) -> Dict[str, float]:
        """
        FSW subsystem readings (meta-telemetry about the FSW itself).

        state_code:  Current state (0=BOOT, 1=NOMINAL, 2=SAFE, 3=CRITICAL).
        uptime_s:    Seconds since FSW started.
        wd_restarts: Number of watchdog restarts since last clean boot.
        """
        uptime = time.monotonic() - self._start_time

        return {
            "state_code": float(self._fsw_state_code),
            "uptime_s": round(uptime, 1),
            "wd_restarts": float(self._wd_restarts),
        }

    # -------------------------------------------------------------------
    # Hardware Interface — Raspberry Pi CPU Temperature
    # -------------------------------------------------------------------

    @staticmethod
    def _read_rpi_cpu_temp() -> float:
        """
        Read real CPU temperature from Raspberry Pi via vcgencmd.

        Returns:
            CPU temperature in C.
            Falls back to 55.0 if vcgencmd is not available.
        """
        try:
            result = subprocess.run(
                ["vcgencmd", "measure_temp"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0:
                # Output format: "temp=55.0'C"
                temp_str = (result.stdout.strip()
                            .replace("temp=", "")
                            .replace("'C", ""))
                return float(temp_str)
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass

        return 55.0  # Fallback: nominal temperature
