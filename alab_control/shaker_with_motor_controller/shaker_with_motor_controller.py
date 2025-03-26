import time
from enum import Enum

from alab_control._base_arduino_device import BaseArduinoDevice
from alab_control.shaker_with_motor_controller.motor_controller import *
import threading
import signal

signal.signal(signal.SIGINT, signal.SIG_DFL)

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

    FREQUENCY = 25 # the frequency of the shaker

    ENDPOINTS = {
        "close gripper": "/gripper-close",
        "open gripper": "/gripper-open",
        "state": "/state",
        "reset": "/reset",
    }

    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)
        self.motor_controller = MotorController(dt=0.1)
        self.motor_controller.set_controller(kp, ki, kd, integral_contribution_limit)
        self.stop_event = threading.Event()  # Stop event for clean shutdown
        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, sig, frame):
        print(f"CTRL+C detected! Stopping motor... (Signal: {sig}, Frame: {frame})")
        self.stop_event.set()  # Tell the thread to stop
        try:
            self.motor_controller.stop()
        except Exception as e:
            print(f"Error stopping motor: {e}")
        finally:
            exit(1)

    def get_state(self):
        """
        Get current status of the shaker machine and the gripper
        """
        response = self.send_request(self.ENDPOINTS["state"], suppress_error=True, timeout=10, max_retries=5)
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

    def close_gripper(self):
        """
        Close the gripper to hold the container
        """
        state=self.get_state()
        print(f"{self.get_current_time()} Gripping the container")
        self.send_request(self.ENDPOINTS["close gripper"], suppress_error=True, timeout=10, max_retries=3)
        while not (GripperWMCState(state["gripper_status"]) == GripperWMCState.CLOSE):
            state = self.get_state()
            if SystemState(state["system_status"]) == SystemState.ERROR:
                raise ShakerWMCError("Shaker machine is in error state. Failed to grip.")
            time.sleep(1)
        if int(state["force_reading"]) > 200:
            raise ShakerWMCError("Gripper is not fully closed or has lost grip.")

    def open_gripper(self):
        """
        Open the gripper to release the container
        """
        state=self.get_state()
        print(f"{self.get_current_time()} Releasing the gripper")
        self.send_request(self.ENDPOINTS["open gripper"], suppress_error=True, timeout=10, max_retries=3)
        while not (GripperWMCState(state["gripper_status"]) == GripperWMCState.OPEN):
            state = self.get_state()
            if SystemState(state["system_status"]) == SystemState.ERROR:
                raise ShakerWMCError("Shaker machine is in error state. Failed to release.")
            time.sleep(1)
        if int(state["force_reading"]) < 200:
            raise ShakerWMCError("Gripper is not fully open or something is attached to the upper part.")

    def shaking(self, duration_sec: float, frequency: int = FREQUENCY):
        """
        Start the shaker machine for a given duration (seconds) and frequency.
        If the gripper is closed, it will check if the gripper is holding the container.

        Args:
            duration_sec: duration of shaking in seconds.
            frequency: frequency of the shaker in Hz.
        """
        self.stop_event.clear()
        generator=DiscreteSpeedProfileGenerator(acceleration=30.0,speed_list=[frequency],duration_list=[duration_sec],dt=0.01)
        generator.generate_profile()
        time_points=generator.time_points
        speed_values=generator.speed_values
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
        self.motor_controller.stop()

    def __del__(self):
        self.stop()