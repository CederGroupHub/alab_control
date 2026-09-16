

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
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
    DASH vertical shaker: Arduino gripper over Ethernet, mill motor over Phidget USB.
    """

    FREQUENCY = 51  # the frequency of the shaker

    # FSR is ~1000 unloaded. Arduino may stop close on a small relative drop
    # (FORCE_DROP_DELTA) well above the old Python absolute limit of 200, which
    # rejected valid grips. Only treat near-unloaded readings as a lost grip.
    FORCE_UNLOADED_MIN = 900

    ENDPOINTS = {
        "close gripper": "/gripper-close",
        "open gripper": "/gripper-open",
        "tighten gripper": "/more",
        "state": "/state",
        "reset": "/reset",
    }

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

    def is_gripper_closed(self) -> bool:
        """
        Check if the gripper is closed
        """
        state = self.get_state()
        if GripperWMCState(state["gripper_status"]) == GripperWMCState.CLOSE:
            return True
        return False

    def close_gripper(self, check_force: bool = True):
        """
        Close the gripper to hold the container.

        Arduino firmware still stops the jaws when its FSR limit is hit.
        When check_force is True (default), Python also rejects CLOSE+ERROR or
        near-unloaded force readings. When False, wait for CLOSE then return
        even if the FSR trip never happened (so shaking can still run).
        """
        state = self.get_state()
        if SystemState(state["system_status"]) == SystemState.ERROR:
            logger.warning(
                f"{self.get_current_time()} Arduino in ERROR before grip; resetting"
            )
            self.reset()
            state = self.get_state()

        logger.info(f"{self.get_current_time()} Gripping the container")
        self.send_request(
            self.ENDPOINTS["close gripper"],
            suppress_error=True,
            timeout=10,
            max_retries=3,
        )
        while GripperWMCState(state["gripper_status"]) != GripperWMCState.CLOSE:
            state = self.get_state()
            if SystemState(state["system_status"]) == SystemState.ERROR:
                # Firmware sets CLOSE+ERROR together when max travel is hit
                # without an FSR trip; exit the wait and decide below.
                if GripperWMCState(state["gripper_status"]) == GripperWMCState.CLOSE:
                    break
                if check_force:
                    force = state.get("force_reading")
                    raise ShakerWMCError(
                        f"Shaker machine is in error state. Failed to grip "
                        f"(force_reading={force}). Try reset, then close again."
                    )
                break
            time.sleep(1)

        state = self.get_state()
        force = int(state["force_reading"])
        if not check_force:
            logger.info(
                f"{self.get_current_time()} Close done without force check "
                f"(gripper={state['gripper_status']}, "
                f"system={state['system_status']}, force_reading={force})"
            )
            return

        if force >= self.FORCE_UNLOADED_MIN:
            raise ShakerWMCError(
                f"Gripper reports CLOSE but force_reading={force} still looks "
                f"unloaded (expected a drop well below {self.FORCE_UNLOADED_MIN})."
            )
        if SystemState(state["system_status"]) == SystemState.ERROR:
            # Firmware sets ERROR when close hits MAG_MIN without an FSR trip,
            # even when the jaws are clearly holding (force already dropped a lot).
            # Keep the grip and continue; mill shake is Phidget-side.
            logger.warning(
                f"{self.get_current_time()} Arduino ERROR after close but "
                f"force_reading={force} looks gripped; continuing"
            )
        else:
            logger.info(
                f"{self.get_current_time()} Grip OK "
                f"(force_reading={force}, status={state['system_status']})"
            )

    def tighten_gripper(self, steps: int = 1):
        """
        After a normal FSR stop, retract a few more MAG_DELTA steps (HTTP /more).

        Requires the sep15+ Arduino sketch that exposes GET /more. One step is a
        small extra squeeze past the force trip; firmware caps pending at 20.
        """
        steps = max(1, min(int(steps), 20))
        logger.info(
            f"{self.get_current_time()} Tightening gripper by {steps} extra step(s)"
        )
        for _ in range(steps):
            self.send_request(
                self.ENDPOINTS["tighten gripper"],
                suppress_error=True,
                timeout=10,
                max_retries=3,
            )
        # Each step is ~500 ms on the Arduino; wait until IDLE again.
        deadline = time.time() + max(10.0, steps * 2.0 + 5.0)
        state = self.get_state()
        while time.time() < deadline:
            if SystemState(state["system_status"]) == SystemState.IDLE:
                break
            state = self.get_state()
        logger.info(
            f"{self.get_current_time()} Tighten done "
            f"(mag={state.get('mag')}, force_reading={state.get('force_reading')}, "
            f"status={state.get('system_status')})"
        )
        return state

    def open_gripper(self, check_force: bool = True):
        """
        Open the gripper to release the container.

        When check_force is False, wait for OPEN (or ERROR) and return without
        validating the unloaded force reading.
        """
        state = self.get_state()
        if SystemState(state["system_status"]) == SystemState.ERROR:
            logger.warning(
                f"{self.get_current_time()} Arduino in ERROR before open; resetting"
            )
            self.reset()
            state = self.get_state()

        logger.info(f"{self.get_current_time()} Releasing the gripper")
        self.send_request(
            self.ENDPOINTS["open gripper"],
            suppress_error=True,
            timeout=10,
            max_retries=3,
        )
        while GripperWMCState(state["gripper_status"]) != GripperWMCState.OPEN:
            state = self.get_state()
            if SystemState(state["system_status"]) == SystemState.ERROR:
                if check_force:
                    raise ShakerWMCError(
                        "Shaker machine is in error state. Failed to release."
                    )
                break
            time.sleep(1)
        if not check_force:
            return
        state = self.get_state()
        force = int(state["force_reading"])
        if force < self.FORCE_UNLOADED_MIN:
            raise ShakerWMCError(
                f"Gripper reports OPEN but force_reading={force} still looks "
                f"loaded (expected >= {self.FORCE_UNLOADED_MIN})."
            )

    def shaking(
        self,
        duration_sec: float,
        frequency: int = FREQUENCY,
        ignore_arduino_error: bool = False,
    ):
        """
        Run the mill for a given duration (seconds) and frequency via Phidget USB.
        Shakes whether or not an object is detected in the gripper.

        Args:
            duration_sec: duration of shaking in seconds.
            frequency: frequency of the shaker in Hz.
            ignore_arduino_error: if True, never abort on Arduino ERROR (use when
                shaking after a close that may not have hit the FSR trip).
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
                if self.stop_event.is_set():
                    self.motor_controller.stop()
                    thread.join(timeout=10)
                    return
                state = self.get_state()
                if SystemState(state["system_status"]) == SystemState.ERROR:
                    if ignore_arduino_error:
                        time.sleep(0.1)
                        continue
                    # Arduino ERROR is usually a grip/FSR false fail; mill is Phidget.
                    # Only abort if the jaws look unloaded while we expect a hold.
                    force = int(state.get("force_reading", 0))
                    grip = GripperWMCState(state["gripper_status"])
                    if grip != GripperWMCState.CLOSE or force >= self.FORCE_UNLOADED_MIN:
                        raise ShakerWMCError(
                            f"Shaker machine is in error state "
                            f"(gripper={grip.value}, force_reading={force})."
                        )
                    logger.warning(
                        f"{self.get_current_time()} Ignoring Arduino ERROR during "
                        f"shake (gripper CLOSE, force_reading={force})"
                    )
                time.sleep(0.1)
        except ShakerWMCError:
            self.motor_controller.stop()
            thread.join(timeout=10)
            raise
        finally:
            self.motor_controller.stop()
            thread.join(timeout=10)
            self.stop_event.clear()

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
        Stop the shaker machine.

        Leaves stop_event set so shaking()'s wait loop can see it; that loop
        returns and finishes cleanup. Clearing here raced Ctrl+C shutdown.
        """
        self.stop_event.set()
        self.motor_controller.stop()

    def is_running(self):
        return self.get_state()["system_status"] == SystemState.RUNNING.value
