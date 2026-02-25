"""
Asterion One — sensor_sim Unit Tests
======================================
Tests the SensorSim leaf component.
Reference: Phase 2, Art.5 §3.1.5

Coverage: 18 tests covering all 5 subsystems, override mode,
merge semantics, state updates, error handling, noise, stability.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from flight.sensor_sim import SensorSim  # noqa: E402
from flight.config import FswConfig  # noqa: E402


def make_sim(nominal_temp=55.0, nominal_voltage=5.1, noise=2.0,
             use_real_temp=False):
    config = FswConfig()
    config.SENSOR_NOMINAL_TEMP_C = nominal_temp
    config.SENSOR_NOMINAL_VOLTAGE_V = nominal_voltage
    config.SENSOR_NOISE_AMPLITUDE = noise
    config.SENSOR_USE_REAL_TEMP = use_real_temp
    return SensorSim(config=config)


# --- Test 1: read_all returns all 5 subsystems ---
def test_read_all_returns_five_subsystems():
    sim = make_sim()
    data = sim.read_all()
    assert isinstance(data, dict)
    assert set(data.keys()) == {"THERMAL", "POWER", "CPU", "COMMS", "FSW"}
    for name, metrics in data.items():
        assert isinstance(metrics, dict), f"{name} should be a dict"
        assert len(metrics) > 0, f"{name} should have metrics"


# --- Test 2-6: Each subsystem has correct metric keys ---
def test_thermal_metrics():
    data = make_sim().read_subsystem("THERMAL")
    assert set(data.keys()) == {"cpu_temp_c", "board_temp_c"}


def test_power_metrics():
    data = make_sim().read_subsystem("POWER")
    assert set(data.keys()) == {"voltage_v", "current_ma", "battery_soc", "power_w"}


def test_cpu_metrics():
    data = make_sim().read_subsystem("CPU")
    assert set(data.keys()) == {"cpu_usage_pct", "memory_usage_pct"}


def test_comms_metrics():
    data = make_sim().read_subsystem("COMMS")
    assert set(data.keys()) == {"ws_connected", "msg_queue_depth", "error_rate"}


def test_fsw_metrics():
    data = make_sim().read_subsystem("FSW")
    assert set(data.keys()) == {"state_code", "uptime_s", "wd_restarts"}


# --- Test 7: Nominal values within expected ranges ---
def test_thermal_nominal_range():
    sim = make_sim(nominal_temp=55.0, noise=2.0)
    for _ in range(50):
        data = sim.read_subsystem("THERMAL")
        assert 30.0 < data["cpu_temp_c"] < 80.0


def test_power_nominal_range():
    sim = make_sim(nominal_voltage=5.1, noise=2.0)
    for _ in range(50):
        data = sim.read_subsystem("POWER")
        assert 4.9 < data["voltage_v"] < 5.3
        assert data["current_ma"] >= 0
        assert 0.0 <= data["battery_soc"] <= 1.0
        assert data["power_w"] >= 0


def test_cpu_nominal_range():
    sim = make_sim()
    for _ in range(50):
        data = sim.read_subsystem("CPU")
        assert 0 <= data["cpu_usage_pct"] <= 100
        assert 0 <= data["memory_usage_pct"] <= 100


# --- Test 8: Override mode replaces targeted metrics ---
def test_override_thermal():
    sim = make_sim(nominal_temp=55.0)
    sim.set_override("THERMAL", {"cpu_temp_c": 85.0})
    assert sim.read_subsystem("THERMAL")["cpu_temp_c"] == 85.0


def test_override_power_voltage():
    sim = make_sim()
    sim.set_override("POWER", {"voltage_v": 4.2})
    assert sim.read_subsystem("POWER")["voltage_v"] == 4.2


# --- Test 9: Override merge — unspecified metrics keep synthetic ---
def test_override_merge_keeps_other_metrics():
    sim = make_sim(nominal_temp=55.0)
    sim.set_override("THERMAL", {"cpu_temp_c": 90.0})
    data = sim.read_subsystem("THERMAL")
    assert data["cpu_temp_c"] == 90.0
    assert "board_temp_c" in data
    assert isinstance(data["board_temp_c"], float)


# --- Test 10: clear_override restores normal readings ---
def test_clear_override_single():
    sim = make_sim(nominal_temp=55.0, noise=0.0)
    sim.set_override("THERMAL", {"cpu_temp_c": 85.0})
    assert sim.read_subsystem("THERMAL")["cpu_temp_c"] == 85.0
    sim.clear_override("THERMAL")
    assert sim.read_subsystem("THERMAL")["cpu_temp_c"] == 55.0


# --- Test 11: clear_all_overrides restores all ---
def test_clear_all_overrides():
    sim = make_sim(noise=0.0)
    sim.set_override("THERMAL", {"cpu_temp_c": 90.0})
    sim.set_override("POWER", {"voltage_v": 3.0})
    sim.clear_all_overrides()
    assert sim.read_subsystem("THERMAL")["cpu_temp_c"] == 55.0
    assert abs(sim.read_subsystem("POWER")["voltage_v"] - 5.1) < 0.01


# --- Test 12: Invalid subsystem names ---
def test_set_override_invalid_subsystem():
    sim = make_sim()
    try:
        sim.set_override("INVALID", {"cpu_temp_c": 85.0})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown subsystem" in str(e)


def test_read_subsystem_invalid_name():
    sim = make_sim()
    try:
        sim.read_subsystem("NONEXISTENT")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown subsystem" in str(e)


# --- Test 13: update_fsw_state ---
def test_update_fsw_state():
    sim = make_sim()
    for code in [0, 1, 2, 3]:
        sim.update_fsw_state(code)
        assert sim.read_subsystem("FSW")["state_code"] == float(code)


# --- Test 14: update_comms_status ---
def test_update_comms_connected():
    sim = make_sim()
    assert sim.read_subsystem("COMMS")["ws_connected"] == 0.0
    sim.update_comms_status(connected=True, queue_depth=5)
    data = sim.read_subsystem("COMMS")
    assert data["ws_connected"] == 1.0
    assert data["msg_queue_depth"] == 5.0
    sim.update_comms_status(connected=False, queue_depth=12)
    data = sim.read_subsystem("COMMS")
    assert data["ws_connected"] == 0.0
    assert data["msg_queue_depth"] == 12.0


# --- Test 15: update_wd_restarts ---
def test_update_wd_restarts():
    sim = make_sim()
    assert sim.read_subsystem("FSW")["wd_restarts"] == 0.0
    sim.update_wd_restarts(2)
    assert sim.read_subsystem("FSW")["wd_restarts"] == 2.0


# --- Test 16: update_battery_soc clamps ---
def test_update_battery_soc_clamp():
    sim = make_sim()
    sim.update_battery_soc(0.5)
    assert sim.read_subsystem("POWER")["battery_soc"] == 0.5
    sim.update_battery_soc(1.5)
    assert sim.read_subsystem("POWER")["battery_soc"] == 1.0
    sim.update_battery_soc(-0.3)
    assert sim.read_subsystem("POWER")["battery_soc"] == 0.0


# --- Test 17: Noise produces variation ---
def test_noise_produces_variation():
    sim = make_sim(nominal_temp=55.0, noise=2.0)
    readings = [sim.read_subsystem("THERMAL")["cpu_temp_c"] for _ in range(20)]
    assert len(set(readings)) > 1, "Expected variation with noise active"


def test_zero_noise_produces_constant():
    sim = make_sim(nominal_temp=55.0, noise=0.0)
    readings = [sim.read_subsystem("THERMAL")["cpu_temp_c"] for _ in range(10)]
    assert all(r == 55.0 for r in readings)


# --- Test 18: Stability — 1000 reads without crash ---
def test_stability_1000_reads():
    sim = make_sim()
    for i in range(1000):
        data = sim.read_all()
        assert len(data) == 5
        for name, metrics in data.items():
            for k, v in metrics.items():
                assert isinstance(v, float), f"Iter {i}, {name}.{k}={v} not float"


# --- Test 19: uptime_s increases ---
def test_uptime_increases():
    sim = make_sim()
    t1 = sim.read_subsystem("FSW")["uptime_s"]
    time.sleep(0.05)
    t2 = sim.read_subsystem("FSW")["uptime_s"]
    assert t2 > t1


# --- Test 20: read_all with active overrides ---
def test_read_all_with_overrides():
    sim = make_sim()
    sim.set_override("THERMAL", {"cpu_temp_c": 99.0})
    sim.set_override("POWER", {"voltage_v": 3.0})
    data = sim.read_all()
    assert data["THERMAL"]["cpu_temp_c"] == 99.0
    assert data["POWER"]["voltage_v"] == 3.0
    assert "cpu_usage_pct" in data["CPU"]
    assert "ws_connected" in data["COMMS"]
    assert "state_code" in data["FSW"]


# --- Test 21: Override with extra metric ---
def test_override_extra_metric():
    sim = make_sim()
    sim.set_override("THERMAL", {"cpu_temp_c": 80.0, "heater_active": 1.0})
    data = sim.read_subsystem("THERMAL")
    assert data["cpu_temp_c"] == 80.0
    assert data["heater_active"] == 1.0
    assert "board_temp_c" in data
