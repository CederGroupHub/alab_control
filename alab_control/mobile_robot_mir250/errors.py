"""The failure vocabulary of the MiR250 driver.

Each of these means something different should happen next, which is the only reason they
are separate types:

- :class:`PreflightFailed` -- the cell is not in a state where motion is safe. Nothing has
  moved, and nothing will until the named condition is fixed.
- :class:`MaintenanceRequired` -- a person has to intervene. There is no software recovery,
  so retrying is not just useless, it hides the problem.
- :class:`MissionCancelled` -- someone asked for this work to stop. The robot parks itself
  and the mission is finished, not failed.
- :class:`BatterySuspend` -- the battery policy interrupted the mission at a safe boundary.
  The mission is intact and resumes from the same leg once charged.
- :class:`LegFailed` -- one leg did not complete. Recoverable in principle, which is what
  separates it from the two above.
"""

from __future__ import annotations


class MobileRobotError(RuntimeError):
    """Base class, so a caller can catch everything this driver raises."""


class PreflightFailed(MobileRobotError):
    """A safety precondition was not met, and no motion was commanded."""


class MaintenanceRequired(MobileRobotError):
    """The cell needs a person. Retrying in software cannot fix this.

    ``prompt`` is the operator-facing wording, kept separate from the exception message so
    a device can put it straight into a maintenance request without reformatting.
    """

    def __init__(self, message: str, *, prompt: str = "") -> None:
        super().__init__(message)
        self.prompt = prompt or message


class MissionInterrupted(MobileRobotError):
    """A mission stopped at a safe boundary rather than failing.

    Carries the leg it stopped before, so a resume knows where to pick up and the UI can
    say what will happen next, and the resources still booked at that moment, so the caller
    can release a Labman quadrant instead of holding it through a charge.
    """

    def __init__(
        self,
        message: str,
        *,
        leg_index: int | None = None,
        held_resources: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.leg_index = leg_index
        self.held_resources = held_resources
        #: A :class:`~alab_control.mobile_robot_mir250.engine.MissionResult` describing what
        #: did get done before the stop. The engine attaches it; a caller catching this needs
        #: it to record where the samples actually ended up.
        self.result: object | None = None


class MissionCancelled(MissionInterrupted):
    """The mission was cancelled. It will not resume."""


class BatterySuspend(MissionInterrupted):
    """The battery fell below the working floor. The mission resumes once charged."""

    def __init__(
        self,
        message: str,
        *,
        leg_index: int | None = None,
        held_resources: tuple[str, ...] = (),
        battery: float | None = None,
    ) -> None:
        super().__init__(message, leg_index=leg_index, held_resources=held_resources)
        self.battery = battery


class LegFailed(MobileRobotError):
    """One leg of a mission did not complete."""

    def __init__(self, message: str, *, leg_index: int | None = None) -> None:
        super().__init__(message)
        self.leg_index = leg_index


class RegistryError(MobileRobotError):
    """The station registry is invalid, or disagrees with the live controller."""
