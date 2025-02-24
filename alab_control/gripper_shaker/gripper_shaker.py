import sys
import os

import time
from enum import Enum
from alab_control._base_arduino_device import BaseArduinoDevice

class MotorState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"

class GripperShaker(BaseArduinoDevice):
    ENDPOINTS = {
        "start": "/start",
        "stop": "/stop",
        "repeat": "/repeat",
        "state": "/state"
    }

    def __init__(self, ip_address: str, port: int = 80):
        super().__init__(ip_address, port)
        self.state = MotorState.STOPPED
        self.last_repeat_count = 0
        self.last_delay_time = 0

    def start_motor(self):
        if self.state == MotorState.RUNNING:
            raise RuntimeError("Motor is already running")
        self.send_request(self.ENDPOINTS["start"], method="GET")
        self.state = MotorState.RUNNING

    def stop_motor(self):
        if self.state == MotorState.STOPPED:
            raise RuntimeError("Motor is already stopped")
        self.send_request(self.ENDPOINTS["stop"], method="GET")
        self.state = MotorState.STOPPED
        
    def repeat_motor(self, repeat_count=2, delay_time=1000):
        if self.state == MotorState.RUNNING:
            raise RuntimeError("Motor is already running")
        response = self.send_request(
            f"/repeat?count={repeat_count}&time={delay_time}", 
            method="GET", 
            data={"count": repeat_count, "time": delay_time}
        )
        
        self.last_repeat_count = repeat_count
        self.last_delay_time = delay_time
        self.state = MotorState.RUNNING
        
        total_time = (repeat_count * (delay_time + 200))/ 1000  
        time.sleep(total_time)
        self.state = MotorState.STOPPED
        return response

    def get_state(self):
        response = self.send_request(self.ENDPOINTS["state"], method="GET")
        return {
            "state": MotorState[response["state"]],
            "lastRepeatCount": response["lastRepeatCount"],
            "lastDelayTime": response["lastDelayTime"]
        }

# Example usage
if __name__ == "__main__":
    # Update the port based on your setup
    motor = GripperShaker("192.168.0.39")
    try:
        print("Starting motor...")
        motor.start_motor()
        time.sleep(2)
        
        print("Stopping motor...")
        motor.stop_motor()
        time.sleep(1)
        
        print("Repeating motor action...")
        motor.repeat_motor(5, 200)
        
        print("Current state:", motor.get_state())
        
    except Exception as e:
        print(f"An error occurred: {e}")