# Emma branch

This is the active `emma` development branch for `alab_control`.

Earlier Emma-related driver and packaging work has already been merged into `main`. This branch now tracks ongoing mobile-robot work only.

## Currently working on

Mobile robot edits:

- Split-program mobile robot routing for base and arm moves
- Using small Ability programs instead of Main where appropriate
- Driver/config cleanup for mobile robot control paths

## Recent changes on this branch

- Add split-program mobile robot routing for base and arm moves
- Remove unused `tube_furnace_MTI` submodule from repo configuration

## Related repos

| Repo | Branch | Role |
|------|--------|------|
| `alab_one` | `emma` | Tasks, devices, booking, examples |
| `alab_control` | `emma` | Low-level mobile robot drivers and Ability routing |

## Before merging to `main`

- [ ] Test split-program routing on the blocks mobile robot
- [ ] Confirm base and arm moves behave correctly with small Ability programs
- [ ] Verify Main-program fallback still works when configured
