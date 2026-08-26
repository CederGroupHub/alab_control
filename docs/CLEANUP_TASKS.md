# Cleanup Tasks

This file is a scratchpad for repo cleanup and onboarding fixes that should be tackled over time.

## High Priority

- Improve driver-layer reliability and consistency.
- Make simulation and local development easier without requiring institution-specific knowledge.
- Standardize connection, timeout, and recovery behavior across device drivers.

## TODO

- Audit driver dependencies and document which are optional, machine-specific, or hardware-only.
- Standardize connection lifecycle patterns (`connect`, `disconnect`, timeout, retry, safe stop).
- Improve local simulation documentation for developers working without hardware attached.
- Coordinate with higher layers so optional camera/workflow helpers such as `trying_camera_functionality` live in version control instead of external folders like `Clutter`.

## Notes

- This repo is the hardware/protocol layer. Hidden external dependencies make the whole stack harder to launch and debug.
