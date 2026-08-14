from __future__ import annotations

import threading
import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice
from alab_control.shaker_with_motor_controller.motor_controller import (
    DiscreteSpeedProfileGenerator,
    MotorController,
)

kp = 0.6
ki = 2.112
kd = 0.003409090909090909
integral_contribution_limit = 1.0


class ShakerWMCState(Enum):
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    ON = "ON"
    OFF = "OFF"


class SystemState(Enum):
    RUNNING = "RUNNING"
    IDLE = "IDLE"
    ERROR = "ERROR"


class GripperWMCState(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class ShakerWMCError(Exception):
    """
    Errors returned from shaker APIs
    """


class ShakerWMC(BaseArduinoDevice):
    """
    Shaker machine for ball milling
    """

    FREQUENCY = 25  # the frequency of the shaker

    ENDPOINTS = {
        "close gripper": "/gripper-close",
        "open gripper": "/gripper-open",
        "set gripper": "/gripper-set",
        "state": "/state",
        "reset": "/reset",
    }

    # Default OPEN height in actuator pulse-width microseconds (firmware
    # INITIAL_MAG). Larger us => more open on this gripper.
    DEFAULT_OPEN_US = 1600
    OPEN_US_MIN = 1200
    OPEN_US_MAX = 2000

    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)
        self.motor_controller = MotorController(dt=0.1)
        self.motor_controller.set_controller(kp, ki, kd, integral_contribution_limit)
        self.stop_event = threading.Event()  # Stop event for clean shutdown

    def get_state(self):
        """
        Get current status of the shaker machine and the gripper
        """
        response = self.send_request(
            self.ENDPOINTS["state"], suppress_error=True, timeout=10, max_retries=5
        )
        time.sleep(1)
        return response

    # Firmware open/close definitions (v2_uno_gpss):
    #   OPEN  = actuator pulse width at INITIAL_MAG (1600 us), jaws retracted.
    #           Success flag is gripper_status=OPEN after the open sweep.
    #   CLOSE = sweep pulse width down toward MAG_MIN (1200 us) until the FSR
    #           reads < 150 (grip detected). Empty jaws -> ERROR.
    # force_reading thresholds used by this driver (ADC counts, not newtons):
    FORCE_OPEN_MIN = 200  # after open, force below this => still pressed/jammed
    FORCE_CLOSE_MAX = 200  # after close, force above this => no grip

    def is_gripper_closed(self) -> bool:
        """
        Check if the gripper is closed
        """
        state = self.get_state()
        if GripperWMCState(state["gripper_status"]) == GripperWMCState.CLOSE:
            return True
        return False

    def _poll_state(self) -> dict:
        """Read /state without the extra 1s sleep in get_state()."""
        return self.send_request(
            self.ENDPOINTS["state"], suppress_error=True, timeout=10, max_retries=3
        )

    def _wait_gripper_motion(
        self,
        *,
        target_gripper: GripperWMCState,
        timeout_sec: float,
        allow_error: bool,
        initial_state: dict | None = None,
    ) -> dict:
        """Wait for a gripper command to finish.

        Important: do NOT treat a pre-existing gripper_status as completion.
        The firmware may already report OPEN/CLOSE from a previous command;
        we must observe RUNNING for *this* command, then IDLE (or ERROR).

        A previous bug accepted IDLE+target after 3s even if RUNNING was never
        seen -- that falsely reported success when the flag was already OPEN
        and the new command never actually ran.
        """
        start = time.time()
        deadline = start + timeout_sec
        saw_running = False
        state: dict = initial_state or {}

        if state:
            try:
                if SystemState(state.get("system_status")) == SystemState.RUNNING:
                    saw_running = True
            except ValueError:
                pass

        while time.time() < deadline:
            state = self._poll_state()
            try:
                system = SystemState(state["system_status"])
                gripper = GripperWMCState(state["gripper_status"])
            except (KeyError, ValueError) as exc:
                raise ShakerWMCError(f"Invalid /state payload: {state}") from exc

            if system == SystemState.RUNNING:
                saw_running = True

            # Only treat ERROR as this command's result after we've seen it run.
            if system == SystemState.ERROR:
                if not saw_running:
                    time.sleep(0.2)
                    continue
                if allow_error:
                    return state
                raise ShakerWMCError(
                    "Shaker machine is in error state during gripper motion."
                )

            # Success: this command ran (RUNNING) and finished IDLE at target.
            if (
                saw_running
                and system == SystemState.IDLE
                and gripper == target_gripper
            ):
                return state

            time.sleep(0.2)

        raise ShakerWMCError(
            f"Timed out waiting for gripper to reach {target_gripper.value} "
            f"(saw_running={saw_running}, "
            f"last state: system={state.get('system_status')}, "
            f"gripper={state.get('gripper_status')}, "
            f"force={state.get('force_reading')}, "
            f"actuator_us={state.get('actuator_us')})"
        )

    def close_gripper(self):
        """
        Close the gripper to hold the container.

        Firmware definition: sweep actuator toward closed until FSR detects a
        grip (force_reading < 150). Raises if the controller trips ERROR
        (typical when jaws are empty) or if force stays high after CLOSE.
        """
        print(f"{self.get_current_time()} Gripping the container")
        close_reply = self.send_request(
            self.ENDPOINTS["close gripper"],
            suppress_error=True,
            timeout=10,
            max_retries=3,
        )
        # Close sweep can take several seconds (1600->1200 in steps of 25).
        state = self._wait_gripper_motion(
            target_gripper=GripperWMCState.CLOSE,
            timeout_sec=30,
            allow_error=True,
            initial_state=close_reply if isinstance(close_reply, dict) else None,
        )
        if SystemState(state["system_status"]) == SystemState.ERROR:
            raise ShakerWMCError(
                "Shaker machine is in error state. Failed to grip."
            )
        if int(state["force_reading"]) > self.FORCE_CLOSE_MAX:
            raise ShakerWMCError("Gripper is not fully closed or has lost grip.")

    def open_gripper(self, open_us: int | None = None):
        """
        Open the gripper to a specific height.

        Args:
            open_us: Actuator pulse width in microseconds (firmware open
                "height"). Defaults to DEFAULT_OPEN_US (1600). Valid range
                OPEN_US_MIN..OPEN_US_MAX (1200..2000). Larger => more open.

        Firmware drives the servo to that setpoint, holds it, then sets
        gripper_status=OPEN. Always waits for this command's motion cycle --
        does not return early just because the flag was already OPEN.
        """
        target_us = self.DEFAULT_OPEN_US if open_us is None else int(open_us)
        if not self.OPEN_US_MIN <= target_us <= self.OPEN_US_MAX:
            raise ValueError(
                f"open_us must be between {self.OPEN_US_MIN} and "
                f"{self.OPEN_US_MAX}, got {target_us}"
            )

        print(
            f"{self.get_current_time()} Opening gripper to height "
            f"us={target_us}"
        )
        # New firmware: /gripper-open?us=NNNN. Old firmware ignores the query
        # string and still opens to its built-in 1600 us setpoint.
        open_reply = self.send_request(
            f"{self.ENDPOINTS['open gripper']}?us={target_us}",
            suppress_error=True,
            timeout=10,
            max_retries=3,
        )
        if (
            isinstance(open_reply, dict)
            and open_reply.get("communication_status") not in (None, "SUCCESS")
        ):
            raise ShakerWMCError(
                f"Open command rejected: {open_reply.get('communication_status')} "
                f"({open_reply.get('reason')})"
            )
        state = self._wait_gripper_motion(
            target_gripper=GripperWMCState.OPEN,
            timeout_sec=20,
            allow_error=False,
            initial_state=open_reply if isinstance(open_reply, dict) else None,
        )
        if int(state["force_reading"]) < self.FORCE_OPEN_MIN:
            raise ShakerWMCError(
                "Gripper is not fully open or something is attached to the upper part."
            )
        # After firmware reflash, /state reports actuator_us -- require it to
        # match the commanded open height (within one step).
        if "actuator_us" in state:
            try:
                actual = int(state["actuator_us"])
            except (TypeError, ValueError) as exc:
                raise ShakerWMCError(
                    f"Invalid actuator_us in state: {state.get('actuator_us')}"
                ) from exc
            if abs(actual - target_us) > 25:
                raise ShakerWMCError(
                    f"Open did not reach target height: commanded us={target_us}, "
                    f"actuator_us={actual}"
                )

    def shaking(self, duration_sec: float, frequency: int = FREQUENCY):
        """
        Start the shaker machine for a given duration (seconds) and frequency.
        If the gripper is closed, it will check if the gripper is holding the container.

        Args:
            duration_sec: duration of shaking in seconds.
            frequency: frequency of the shaker in Hz.
        """
        self.stop_event.clear()
        generator = DiscreteSpeedProfileGenerator(
            acceleration=30.0,
            speed_list=[frequency],
            duration_list=[duration_sec],
            dt=0.01,
        )
        generator.generate_profile()
        time_points = generator.time_points
        speed_values = generator.speed_values
        self.motor_controller.set_speed_profile(time_points, speed_values)
        thread = threading.Thread(target=self.motor_controller.run_profile)
        thread.start()
        try:
            while thread.is_alive():
                if self.stop_event.is_set():  # Stop motor if event is set
                    raise KeyboardInterrupt
                state = self.get_state()
                if GripperWMCState(state["gripper_status"]) == GripperWMCState.CLOSE:
                    if int(state["force_reading"]) > 200:
                        raise ShakerWMCError("Gripper is not closed or has lost grip.")
                if SystemState(state["system_status"]) == SystemState.ERROR:
                    raise ShakerWMCError("Shaker machine is in error state.")
                time.sleep(1)
        except (ShakerWMCError, Exception, KeyboardInterrupt) as e:
            self.motor_controller.stop()
            thread.join()
            raise e
        finally:
            self.motor_controller.stop()
            thread.join()

    def close_gripper_and_shake(self, duration_sec: int, frequency: int = FREQUENCY):
        """
        Grip the container, shake it and then release it.

        Args:
            duration_sec: duration of shaking in seconds
            frequency: frequency of the shaker in Hz.
        """
        self.close_gripper()
        time.sleep(3)
        self.shaking(duration_sec=duration_sec, frequency=frequency)
        time.sleep(3)
        self.open_gripper()

    def reset(self):
        """
        Reset the shaker machine
        """
        self.motor_controller.stop()
        self.send_request(self.ENDPOINTS["reset"], timeout=10, max_retries=3)
        time.sleep(8)

    def stop(self):
        """
        Stop the shaker machine
        """
        self.stop_event.set()  # Tell the thread to stop
        self.motor_controller.stop()

    def is_running(self):
        return self.get_state()["system_status"] == SystemState.RUNNING.value
