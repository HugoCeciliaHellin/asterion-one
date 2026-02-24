# ADR-001: Python for Flight Software

**Status:** Accepted  
**Date:** 2026-02-23  
**Context:** REQ-HW-PLATFORM, Lit. Review §4.1

## Decision

The Flight Software (FSW) is implemented in **Python 3.11+** running on a Raspberry Pi 4/5 under Linux, rather than C/C++ as traditionally used in aerospace flight software (NASA cFS, NASA F').

## Rationale

1. **Integration agility.** The Digital Twin uses NumPy for the RC thermal model (REQ-DT-EARLY-15m). Python allows the FSW and Twin to share data types and potentially run in the same process during testing, eliminating serialization overhead. C++ interop with NumPy would introduce pybind11 complexity disproportionate to a desk-scale project.

2. **FDIR architecture discipline, not language.** The Lit. Review §4.1 confirms that PFL (Python Flight Software) validates Python's viability for mission logic. Asterion One enforces NASA-standard FDIR patterns (state machines, watchdog timers, Safe Mode) at the architectural level. The design patterns are ported from cFS, not the C code.

3. **Systemd watchdog compensates for runtime fragility.** Python's interpreter startup time (~300ms) fits within the 3-second recovery budget (REQ-FSW-WD-03s). The external Systemd watchdog provides hardware-level process supervision that is language-agnostic.

4. **Desk-scale scope.** This is not flight-rated software. The project's value is in demonstrating resilience patterns, not in meeting DO-178C certification. Python's productivity advantage directly translates to a more complete system within the dissertation timeline.

## Consequences

- **Positive:** Faster development, rich ecosystem (PyNaCl, websockets, sdnotify), shared language with Twin.
- **Negative:** Higher memory footprint (~50MB vs ~5MB for C). Interpreter startup adds ~300ms to watchdog recovery. No hardware interrupt access (not needed for desk-scale).
- **Mitigated:** Memory limit enforced via Systemd (MemoryMax=256M). Startup cost accepted within 3s budget.

## Alternatives Considered

| Alternative | Reason Rejected |
|-------------|----------------|
| NASA cFS (C) | Infrastructure complexity diverts focus from research goals. Setup takes months. |
| NASA F' (C++) | High barrier for integrating data science libraries needed for Twin. |
| MicroPython | Lacks websockets, PyNaCl, and full asyncio support. |
