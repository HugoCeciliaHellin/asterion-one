# Asterion One

**A Desk-Scale Satellite Mission: Resilient Flight Software, Intermittent Communications, Predictive Digital Twin & Operational Security**

> BSc Computer Science — York St John University  
> Hugo Cecilia Hellin | 250172942  
> Supervisor: Dr Alexandros Evangelidis

---

## Overview

Asterion One is a desk-scale simulation of a satellite mission that demonstrates resilient operations, secure and auditable workflows, and predictive maintenance without specialised space hardware.

The system integrates four segments:

| Segment | Technology | Purpose |
|---------|-----------|---------|
| **Flight Software** | Python 3 / Raspberry Pi | FDIR state machine, watchdog recovery, telemetry |
| **Ground Control** | Node.js + React + PostgreSQL | Dashboard, command planning, audit timeline |
| **Digital Twin** | Python 3 + NumPy | RC thermal model, predictive alerts |
| **Infrastructure** | Docker + Systemd + OTel | Observability, CI, fault injection |

## Research Questions

1. Does contact-window messaging prevent any command loss during planned outages?
2. Can SAFE/NOMINAL + watchdog recover to SAFE in ≤3s and return to NOMINAL safely?
3. Does a first-order RC model give ≥15 min early warnings with clear rationale?

## Quick Start

```bash
# 1. Start infrastructure (PostgreSQL)
docker compose up -d

# 2. Install Flight dependencies
cd flight && pip install -r requirements.txt && cd ..

# 3. Install Twin dependencies
cd twin && pip install -r requirements.txt && cd ..

# 4. Install Ground dependencies
cd ground && npm ci && cd ..

# 5. Run tests
python -m pytest flight/tests/ -v
python -m pytest twin/tests/ -v
cd ground && npm test && cd ..
```

## Directory Structure

```
asterion-one/
├── flight/                  # Flight Segment (Python 3)
│   ├── models.py            # Shared data types
│   ├── config.py            # Configurable parameters
│   ├── fsw_core.py          # State machine + main loop
│   ├── sensor_sim.py        # Telemetry generation
│   ├── comms_client.py      # WebSocket client + Store-and-Forward
│   ├── cmd_executor.py      # Command plan execution
│   ├── crypto_verifier.py   # Ed25519 signature verification
│   ├── audit_logger.py      # Hash-chained audit log
│   ├── disk_queue.py        # Persistent FIFO queue
│   └── tests/               # Unit tests
├── ground/
│   ├── src/                 # Node.js API + services
│   │   ├── api/             # Express REST endpoints
│   │   ├── ws/              # WebSocket gateway
│   │   ├── db/              # Database manager + migrations
│   │   └── services/        # Audit service
│   └── ui/                  # React dashboard (Vite)
│       └── src/
│           ├── views/       # 5 dashboard views
│           └── lib/         # Client-side crypto
├── twin/                    # Digital Twin (Python 3 + NumPy)
│   ├── twin_engine.py       # RC thermal + energy models
│   ├── alert_engine.py      # Threshold evaluation + rationale
│   ├── twin_api.py          # Orchestration cycle
│   └── tests/               # Unit tests
├── infra/
│   ├── fault_injector.py    # Testing CLI (6 commands)
│   ├── systemd/             # asterion-fsw.service
│   └── observability/       # OTel + Prometheus + Grafana + Loki
├── docs/
│   ├── ICD.md               # Interface Control Document
│   ├── ADR/                 # Architecture Decision Records
│   ├── TEST_PLAN.md         # Test Plan (from verification gates)
│   └── DEPLOYMENT_GUIDE.md  # Deployment instructions
├── docker-compose.yml       # Infrastructure orchestration
└── .github/workflows/ci.yml # CI pipeline
```

## Requirements Verified

| ID | Description | Verification |
|----|-------------|-------------|
| REQ-FSW-STATE-01 | Explicit state machine (BOOT/NOMINAL/SAFE/CRITICAL) | Fault injection tests |
| REQ-FSW-WD-03s | Watchdog recovery ≤ 3 seconds | `fault_injector inject kill-process` |
| REQ-FSW-LOG-SECURE | Hash-chained tamper-evident audit log | Chain verification endpoint |
| REQ-COM-ZERO-LOSS | Zero command loss during outages | `fault_injector inject network-outage` |
| REQ-COM-P95 | Command latency ≤ 2s (p95) | Latency statistical analysis |
| REQ-SEC-ED25519 | Ed25519 signed commands, reject invalid | `fault_injector inject bad-signature` |
| REQ-GND-PLAN | Visual contact window scheduling | UI Pass Planner view |
| REQ-OPS-OBSERVABILITY | OpenTelemetry + Grafana stack | Dashboard review |
| REQ-DT-EARLY-15m | Predict violations ≥ 15 min ahead | Thermal simulation test |
| REQ-DT-RATIONALE | Human-readable alert rationale | Rationale content review |

## License

MIT
