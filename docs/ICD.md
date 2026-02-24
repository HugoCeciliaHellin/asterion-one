# Asterion One — Interface Control Document (ICD)

**Status:** DRAFT (v0.1)  
**Last Updated:** 2026-02-23  
**Source:** Phase 2, Artifact 8

> This document is the living ICD for the Asterion One project.
> The initial draft was produced during Phase 2 (Design).
> It is updated incrementally as implementation reveals edge cases.
>
> For the full draft, see: `phase2_artifact08_icd.md`

## Quick Reference

### WebSocket Messages (IF-WS)

| Type | Direction | Reference |
|------|-----------|-----------|
| TELEMETRY | Flight → Ground | IF-WS-001 |
| PLAN_UPLOAD | Ground → Flight | IF-WS-002 |
| COMMAND_ACK | Flight → Ground | IF-WS-003 |
| COMMAND_NACK | Flight → Ground | IF-WS-004 |
| TELEMETRY_ACK | Ground → Flight | IF-WS-005 |
| AUDIT_EVENT | Flight → Ground | IF-WS-006 |
| REPLAY_REQUEST | Flight → Ground | IF-WS-007 |

### REST API Endpoints (IF-REST)

| Endpoint | Methods | Reference |
|----------|---------|-----------|
| /api/contact-windows | GET, POST, PATCH | IF-REST-001 |
| /api/command-plans | POST, PATCH | IF-REST-002 |
| /api/command-plans/:id/upload | POST | IF-REST-002 |
| /api/telemetry | GET, POST | IF-REST-003 |
| /api/events | GET | IF-REST-004 |
| /api/events/verify | GET | IF-REST-004 |
| /api/twin/forecasts | GET, POST | IF-REST-005 |
| /api/twin/alerts | GET | IF-REST-005 |
| /api/health | GET | IF-REST-006 |

### Ports

| Service | Port |
|---------|------|
| Ground REST API | 3000 |
| WebSocket Gateway | 8081 |
| React UI (dev) | 5173 |
| PostgreSQL | 5432 |
| Prometheus | 9090 |
| Grafana | 3001 |
| Loki | 3100 |
