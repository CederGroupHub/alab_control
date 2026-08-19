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
- :class:`ObstructionHold` -- something was in the way and re-approaching did not help. Like
  a battery suspend the mission is intact and resumes from the same leg, but unlike one it
  cannot resume on its own, because only a person can move the obstruction.
- :class:`LegFailed` -- one leg did not complete. Recoverable in principle, which is what
  separates it from the two above.
- :class:`ObstructionDetected` -- a single drive was stopped because the base stopped making
  progress. A `LegFailed`, so the ordinary retry policy sees it first; it only becomes an
  `ObstructionHold` once the re-approaches are used up.
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


class ObstructionHold(MissionInterrupted):
    """Something is in the way. The mission waits for a person, then resumes.

    ``obstruction`` is the :class:`~alab_control.mobile_robot_mir250.obstruction.Obstruction`
    that caused it, carrying the map coordinates of the spot to go and inspect, and
    ``prompt`` is the operator-facing wording. Held separately from the message for the same
    reason as :class:`MaintenanceRequired`: a device puts it straight into a request.
    """

    def __init__(
        self,
        message: str,
        *,
        leg_index: int | None = None,
        held_resources: tuple[str, ...] = (),
        obstruction: object | None = None,
        prompt: str = "",
    ) -> None:
        super().__init__(message, leg_index=leg_index, held_resources=held_resources)
        self.obstruction = obstruction
        self.prompt = prompt or message

    @property
    def latched(self) -> bool:
        """Whether the controller was emergency-stopped, so the robot cannot drive itself.

        Asked by every caller that would otherwise dock the robot. Answered from the
        exception rather than from a flag the caller has to remember to check, because a
        handler that forgets would command a collided robot to drive across the cell.
        """
        return False


class CollisionStop(ObstructionHold):
    """The base hit something, or something appeared in front of it, so it was latched.

    A subclass of :class:`ObstructionHold` because everything about the aftermath is the
    same -- the mission is intact, the gripper is empty, a person has to clear the path and
    say so before anything resumes -- and separate because two things are not the same:

    - the controller is emergency-stopped, so the robot cannot drive itself to the charger
      and must not be asked to
    - it needs a physical reset at the robot, which no amount of software can do

    Handlers that catch :class:`ObstructionHold` will catch this too, which is why
    :attr:`latched` exists rather than a separate code path they might not have.
    """

    @property
    def latched(self) -> bool:
        return True


class LegFailed(MobileRobotError):
    """One leg of a mission did not complete."""

    def __init__(self, message: str, *, leg_index: int | None = None) -> None:
        super().__init__(message)
        self.leg_index = leg_index


class ObstructionDetected(LegFailed):
    """A drive was stopped because the base stopped getting closer to its target.

    A `LegFailed` on purpose, so `run_leg_with_retries` handles it like any other
    recoverable leg failure and gets to try re-approaching before anyone is asked to help.
    """

    def __init__(
        self,
        message: str,
        *,
        leg_index: int | None = None,
        obstruction: object | None = None,
    ) -> None:
        super().__init__(message, leg_index=leg_index)
        self.obstruction = obstruction


class RegistryError(MobileRobotError):
    """The station registry is invalid, or disagrees with the live controller."""
