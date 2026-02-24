#!/usr/bin/env python3
"""
Asterion One — Fault Injector CLI
==================================
First-class testing component for requirement verification.
Reference: Phase 2, Art.5 §3.4.2 — fault_injector

Each subcommand injects a specific fault and produces a JSON report
with {injection_type, injected_at, detected_at, recovered_at,
recovery_time_ms, target_ms, pass: true/false}.

Phase 1 commands (implemented):
  kill-process     — SIGKILL fsw_core, measure WD recovery [REQ-FSW-WD-03s]
  thermal-spike    — Override sensor temp, trigger T3 [REQ-FSW-STATE-01]
  power-drop       — Override voltage, trigger T3 [REQ-FSW-STATE-01]
  cascade-failure  — 3x kill-process → verify T6 [REQ-FSW-STATE-01]

Phase 2 commands (skeleton):
  network-outage   — Force link CLOSED [REQ-COM-ZERO-LOSS]

Phase 3 commands (skeleton):
  bad-signature    — Send plan with corrupted sig [REQ-SEC-ED25519]

Usage:
  python fault_injector.py inject kill-process
  python fault_injector.py inject thermal-spike --temp 85 --duration 60
  python fault_injector.py inject cascade-failure
  python fault_injector.py run-all --output results/
"""

import argparse
import json
import os
import sys
import time
import tempfile
import threading
from datetime import datetime, timezone


def _timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _report(injection_type: str, result: dict) -> dict:
    """Print and return a standardized JSON report."""
    report = {
        "injection_type": injection_type,
        "timestamp": _timestamp(),
        **result,
    }
    print(json.dumps(report, indent=2))
    return report


# ---------------------------------------------------------------------------
# Shared: create a running FswCore in a background thread
# ---------------------------------------------------------------------------

def _create_fsw(
    stability_timer=0.5,
    max_wd_restarts=3,
    temp_warn=75.0,
    hysteresis=5.0,
    telem_safe_rate=0.1,
):
    """
    Create an FswCore instance with test-friendly config and
    start it in a background thread.

    Returns: (fsw, thread, tmp_dir)
    """
    # Add project root to path
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from flight.fsw_core import FswCore
    from flight.config import FswConfig

    tmp_dir = tempfile.mkdtemp()
    config = FswConfig()
    config.TICK_INTERVAL_SEC = 0.05
    config.STABILITY_TIMER_SEC = stability_timer
    config.THRESHOLD_TEMP_WARN_C = temp_warn
    config.HYSTERESIS_TEMP_C = hysteresis
    config.MAX_WD_RESTARTS = max_wd_restarts
    config.SENSOR_NOISE_AMPLITUDE = 0.0
    config.SENSOR_NOMINAL_TEMP_C = 55.0
    config.SENSOR_NOMINAL_VOLTAGE_V = 5.1
    config.TELEMETRY_RATE_SAFE_SEC = telem_safe_rate
    config.AUDIT_LOG_PATH = os.path.join(tmp_dir, "audit.jsonl")
    config.QUEUE_DIR = os.path.join(tmp_dir, "queue")
    config.TRUSTED_KEYS_PATH = "/tmp/nonexistent.json"

    os.environ.pop("RECOVERY_MODE", None)

    fsw = FswCore(config=config)
    fsw._boot_counter_path = os.path.join(tmp_dir, "boot_counter")

    return fsw, tmp_dir


def _run_fsw_loop(fsw, stop_event):
    """Run FSW main loop until stop_event is set."""
    fsw.start()
    while not stop_event.is_set():
        fsw.tick()
        time.sleep(fsw.config.TICK_INTERVAL_SEC)


# ---------------------------------------------------------------------------
# Phase 1 Command: kill-process
# ---------------------------------------------------------------------------

def cmd_kill_process(args):
    """
    Simulate watchdog recovery by killing the FSW main loop.

    Since we can't use real Systemd in test, we simulate:
      1. Start FSW in NOMINAL
      2. Record timestamp
      3. Stop FSW (simulates SIGKILL)
      4. Restart with RECOVERY_MODE=SAFE
      5. Measure time to reach SAFE state

    Requirement: REQ-FSW-WD-03s (recovery ≤ 3000ms)
    Reference: Art.6 UC-09, Art.7 SD-3
    """
    sys.path.insert(0, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")))
    from flight.fsw_core import FswCore
    from flight.models import FswState

    print("[kill-process] Starting FSW in NOMINAL...")
    fsw, tmp_dir = _create_fsw()
    fsw.start()
    fsw.tick()  # BOOT → NOMINAL
    assert fsw.state == FswState.NOMINAL, \
        f"Expected NOMINAL, got {fsw.state}"

    print("[kill-process] Simulating SIGKILL...")
    injected_at = time.monotonic()
    fsw.stop()  # Simulates process death

    # Simulate Systemd restart with RECOVERY_MODE=SAFE
    os.environ["RECOVERY_MODE"] = "SAFE"

    print("[kill-process] Restarting with RECOVERY_MODE=SAFE...")
    from flight.config import FswConfig
    config = fsw.config
    fsw2 = FswCore(config=config)
    fsw2._boot_counter_path = os.path.join(tmp_dir, "boot_counter")

    fsw2.start()
    recovered_at = time.monotonic()

    recovery_ms = (recovered_at - injected_at) * 1000

    os.environ.pop("RECOVERY_MODE", None)

    passed = (fsw2.state == FswState.SAFE and recovery_ms <= 3000)

    _report("kill-process", {
        "status": "COMPLETED",
        "fsw_state_after": fsw2.state.value,
        "recovery_time_ms": round(recovery_ms, 2),
        "target_ms": 3000,
        "wd_restarts": fsw2.consecutive_wd_restarts,
        "pass": passed,
    })

    sys.exit(0 if passed else 1)


# ---------------------------------------------------------------------------
# Phase 1 Command: thermal-spike
# ---------------------------------------------------------------------------

def cmd_thermal_spike(args):
    """
    Inject a thermal spike via sensor override, verify T3 triggers.

    Flow:
      1. Start FSW in NOMINAL
      2. Override cpu_temp_c to args.temp (above threshold)
      3. Tick → verify state transitions to SAFE (T3)
      4. Hold for args.duration ticks
      5. Clear override → verify recovery (T5) if duration allows

    Requirement: REQ-FSW-STATE-01 (T3: NOMINAL→SAFE)
    Reference: Art.6 UC-10, Art.7 SD-5
    """
    sys.path.insert(0, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")))
    from flight.fsw_core import FswCore
    from flight.models import FswState

    temp = args.temp
    duration = args.duration

    print(f"[thermal-spike] Injecting temp={temp}°C for {duration}s...")

    fsw, tmp_dir = _create_fsw(
        stability_timer=0.5,
        telem_safe_rate=0.01,
    )
    fsw.start()
    fsw.tick()  # BOOT → NOMINAL
    assert fsw.state == FswState.NOMINAL

    # Inject thermal spike
    injected_at = time.monotonic()
    fsw.sensors.set_override("THERMAL", {"cpu_temp_c": temp})

    fsw.tick()  # Should trigger T3
    detected_at = time.monotonic()
    detection_ms = (detected_at - injected_at) * 1000

    t3_triggered = (fsw.state == FswState.SAFE)

    # Hold fault for specified duration (simulated ticks)
    hold_ticks = min(duration, 10)  # Cap for test speed
    for _ in range(hold_ticks):
        fsw.tick()
        time.sleep(0.05)

    # Clear override and verify recovery
    fsw.sensors.clear_all_overrides()
    recovery_start = time.monotonic()

    # Tick until recovery or timeout
    recovered = False
    for _ in range(100):
        fsw.tick()
        if fsw.state == FswState.NOMINAL:
            recovered = True
            break
        time.sleep(0.05)

    recovery_ms = (time.monotonic() - recovery_start) * 1000

    # Check audit for T3 event
    entries = fsw.audit.get_entries()
    t3_entries = [e for e in entries
                  if "T3" in e.description
                  and e.event_type == "STATE_TRANSITION"]

    passed = t3_triggered and len(t3_entries) > 0

    _report("thermal-spike", {
        "status": "COMPLETED",
        "temp_c": temp,
        "duration_s": duration,
        "t3_triggered": t3_triggered,
        "detection_time_ms": round(detection_ms, 2),
        "t3_audit_events": len(t3_entries),
        "recovered_to_nominal": recovered,
        "recovery_time_ms": round(recovery_ms, 2) if recovered else None,
        "pass": passed,
    })

    sys.exit(0 if passed else 1)


# ---------------------------------------------------------------------------
# Phase 1 Command: power-drop
# ---------------------------------------------------------------------------

def cmd_power_drop(args):
    """
    Inject a voltage drop via sensor override, verify T3 triggers.

    Requirement: REQ-FSW-STATE-01 (T3: NOMINAL→SAFE via voltage)
    """
    sys.path.insert(0, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")))
    from flight.fsw_core import FswCore
    from flight.models import FswState

    voltage = args.voltage
    duration = args.duration

    print(f"[power-drop] Injecting voltage={voltage}V for {duration}s...")

    fsw, tmp_dir = _create_fsw(telem_safe_rate=0.01)
    fsw.start()
    fsw.tick()  # BOOT → NOMINAL
    assert fsw.state == FswState.NOMINAL

    injected_at = time.monotonic()
    fsw.sensors.set_override("POWER", {"voltage_v": voltage})

    fsw.tick()
    detected_at = time.monotonic()
    t3_triggered = (fsw.state == FswState.SAFE)

    passed = t3_triggered

    _report("power-drop", {
        "status": "COMPLETED",
        "voltage_v": voltage,
        "t3_triggered": t3_triggered,
        "detection_time_ms": round((detected_at - injected_at) * 1000, 2),
        "pass": passed,
    })

    sys.exit(0 if passed else 1)


# ---------------------------------------------------------------------------
# Phase 1 Command: cascade-failure
# ---------------------------------------------------------------------------

def cmd_cascade_failure(args):
    """
    Simulate 3+ consecutive watchdog restarts → verify T6 escalation.

    Flow:
      1. Start FSW normally → NOMINAL
      2. Simulate 1st WD restart → SAFE (restart #1)
      3. Simulate 2nd WD restart → SAFE (restart #2)
      4. Simulate 3rd WD restart → SAFE (restart #3)
      5. Simulate 4th WD restart → CRITICAL (T6: restart #4 > MAX=3)

    Requirement: REQ-FSW-STATE-01 (T6: SAFE→CRITICAL)
    Reference: Art.6 UC-13, Art.3 §5.3 Escalation Policy
    """
    sys.path.insert(0, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")))
    from flight.fsw_core import FswCore
    from flight.models import FswState

    max_restarts = 3

    print(f"[cascade-failure] Simulating {max_restarts + 1} consecutive "
          f"WD restarts (max={max_restarts})...")

    fsw, tmp_dir = _create_fsw(max_wd_restarts=max_restarts)
    boot_counter_path = os.path.join(tmp_dir, "boot_counter")

    states_after_restart = []

    # Simulate consecutive restarts
    for restart_num in range(max_restarts + 1):
        # Save boot counter (simulates persistent counter across restarts)
        with open(boot_counter_path, "w") as f:
            f.write(str(restart_num))

        os.environ["RECOVERY_MODE"] = "SAFE"

        from flight.config import FswConfig
        config = FswConfig()
        config.TICK_INTERVAL_SEC = 0.01
        config.MAX_WD_RESTARTS = max_restarts
        config.SENSOR_NOISE_AMPLITUDE = 0.0
        config.AUDIT_LOG_PATH = os.path.join(tmp_dir, f"audit_{restart_num}.jsonl")
        config.QUEUE_DIR = os.path.join(tmp_dir, "queue")
        config.TRUSTED_KEYS_PATH = "/tmp/nonexistent.json"
        config.TELEMETRY_RATE_SAFE_SEC = 0.01

        fsw_i = FswCore(config=config)
        fsw_i._boot_counter_path = boot_counter_path
        fsw_i.start()

        states_after_restart.append({
            "restart_num": restart_num + 1,
            "state": fsw_i.state.value,
            "wd_restarts": fsw_i.consecutive_wd_restarts,
        })

        print(f"  Restart #{restart_num + 1}: state={fsw_i.state.value}, "
              f"wd_count={fsw_i.consecutive_wd_restarts}")

    os.environ.pop("RECOVERY_MODE", None)

    # Verify: restarts 1-3 → SAFE, restart 4 → CRITICAL
    last = states_after_restart[-1]
    t6_triggered = (last["state"] == "CRITICAL")
    all_safe_before = all(
        s["state"] == "SAFE"
        for s in states_after_restart[:-1]
    )

    passed = t6_triggered and all_safe_before

    _report("cascade-failure", {
        "status": "COMPLETED",
        "max_restarts": max_restarts,
        "restarts": states_after_restart,
        "t6_triggered": t6_triggered,
        "all_safe_before_escalation": all_safe_before,
        "pass": passed,
    })

    sys.exit(0 if passed else 1)


# ---------------------------------------------------------------------------
# Phase 2 Skeleton: network-outage
# ---------------------------------------------------------------------------

def cmd_network_outage(args):
    """Phase 2: Instruct window_scheduler to force CLOSED."""
    print(f"[PHASE 2] inject network-outage --duration {args.duration} "
          f"— NOT YET IMPLEMENTED")
    _report("network-outage", {
        "status": "NOT_IMPLEMENTED",
        "duration_s": args.duration,
        "pass": None,
    })
    sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 3 Skeleton: bad-signature
# ---------------------------------------------------------------------------

def cmd_bad_signature(args):
    """Phase 3: Send plan with corrupted Ed25519 signature."""
    print("[PHASE 3] inject bad-signature — NOT YET IMPLEMENTED")
    _report("bad-signature", {
        "status": "NOT_IMPLEMENTED",
        "pass": None,
    })
    sys.exit(1)


# ---------------------------------------------------------------------------
# Phase 5: run-all
# ---------------------------------------------------------------------------

def cmd_run_all(args):
    """Execute all injection tests sequentially, collect results."""
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    print(f"[run-all] Output directory: {output_dir}")
    print(f"[run-all] NOT FULLY IMPLEMENTED — Phase 5")
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fault_injector",
        description=(
            "Asterion One — Fault Injector CLI\n"
            "Injects controlled faults for requirement verification.\n"
            "Reference: Phase 2, Art.5 §3.4.2"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- inject ---
    inject_parser = subparsers.add_parser("inject", help="Inject a fault")
    inject_sub = inject_parser.add_subparsers(dest="fault_type", help="Fault type")

    # kill-process
    p = inject_sub.add_parser("kill-process",
        help="Simulate WD recovery [REQ-FSW-WD-03s]")
    p.set_defaults(func=cmd_kill_process)

    # thermal-spike
    p = inject_sub.add_parser("thermal-spike",
        help="Force high temp, trigger T3 [REQ-FSW-STATE-01]")
    p.add_argument("--temp", type=float, default=85.0,
        help="Target temperature °C (default: 85.0)")
    p.add_argument("--duration", type=int, default=60,
        help="Duration of spike in seconds (default: 60)")
    p.set_defaults(func=cmd_thermal_spike)

    # power-drop
    p = inject_sub.add_parser("power-drop",
        help="Force low voltage, trigger T3 [REQ-FSW-STATE-01]")
    p.add_argument("--voltage", type=float, default=4.2,
        help="Target voltage V (default: 4.2)")
    p.add_argument("--duration", type=int, default=60,
        help="Duration seconds (default: 60)")
    p.set_defaults(func=cmd_power_drop)

    # cascade-failure
    p = inject_sub.add_parser("cascade-failure",
        help="3x kill → verify T6 [REQ-FSW-STATE-01]")
    p.set_defaults(func=cmd_cascade_failure)

    # network-outage
    p = inject_sub.add_parser("network-outage",
        help="Force link CLOSED [REQ-COM-ZERO-LOSS] (Phase 2)")
    p.add_argument("--duration", type=int, default=120,
        help="Outage seconds (default: 120)")
    p.set_defaults(func=cmd_network_outage)

    # bad-signature
    p = inject_sub.add_parser("bad-signature",
        help="Corrupted Ed25519 sig [REQ-SEC-ED25519] (Phase 3)")
    p.set_defaults(func=cmd_bad_signature)

    # --- run-all ---
    p = subparsers.add_parser("run-all",
        help="Execute all tests (Phase 5)")
    p.add_argument("--output", type=str, default="results/",
        help="Output dir (default: results/)")
    p.set_defaults(func=cmd_run_all)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
