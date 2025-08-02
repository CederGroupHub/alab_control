import time
from enum import Enum

import requests

class MRAState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"

class MobileRobotArm():
    """
    Mobile Robot Arm.
    """

    def __init__(self, ip: str = "192.168.1.207"):
        self.ip = ip
        self.state, self.message = self.get_state_and_message()
        self.battery_level = self.get_battery_level()

    def request_status(self) -> dict:
        """
        Request the status of the MRA.
        """
        response = requests.get(f"http://{self.ip}:8082/v2/status")
        if response.status_code != 200:
            raise ValueError(f"Failed to get status. Status code: {response.status_code}. Response: {response.text}")
        return response.json()

    def get_state_and_message(self) -> tuple[MRAState, str]:
        """
        Return the state of the MRA and the message if there is any.
        This is the API documentation:
        https://docs.alabos.com/alabOS/api/mobile-robot-arm/
        """
        # send a get request to http://192.168.1.207:8082/v2/status
        # this is an example response:
        # {
        #     "state": "Idle",
        #     "current_program": {
        #         "name": "Initialize",
        #         "id": "",
        #         "arguments": [],
        #         "started_at": "",
        #         "completed_at": "",
        #         "state": 0,
        #         "state_text": "",
        #         "message": "",
        #         "in_line_program": "",
        #         "webhook": {
        #             "uri": "",
        #             "context": ""
        #         }
        #     },
        #     "battery": 100,
        #     "message": ""
        # }
        response = self.request_status()
        state = response["state"]
        if state == "Idle" or state == "Ready":
            return MRAState.IDLE, response.json()["message"]
        elif state == "Executing":
            return MRAState.RUNNING, response.json()["message"]
        elif state == "Execution Error Active":
            return MRAState.ERROR, response.json()["message"]
        else:
            raise ValueError(f"Unknown state: {state}. Please check the API documentation for the full list of states.")
        
    def acknowledge_error(self):
        # send a put request to http://192.168.1.207:8082/v2/status with the following body:
        # {
        #     "state": "Ready"
        # }
        response = requests.put(f"http://{self.ip}:8082/v2/status", json={"state": "Ready"})
        if response.status_code != 200:
            raise ValueError(f"Failed to acknowledge error. Status code: {response.status_code}. Response: {response.text}")
        
    def get_battery_level(self) -> float:
        # send a get request to http://192.168.1.207:8082/v2/status
        # this is an example response:
        # {
        #     "battery": 100
        # }
        response = self.request_status()
        return float(response["battery"])
    
    def get_current_program(self) -> dict:
        # send a get request to http://192.168.1.207:8082/v2/status
        response = self.request_status()
        return response["current_program"]
    
    def load_program(self, program_name: str, arguments: list[dict]):
        # send a put request to http://192.168.1.207:8082/v2/programs/current with the following body example:
        # {
        #     "name": "string",
        #     "arguments": [
        #         {
        #             "name": "string",
        #             "type": 0,
        #             "value": "string"
        #         }
        #     ]
        # }
        response = requests.put(f"http://{self.ip}:8082/v2/programs/current", json={"name": program_name, "arguments": arguments})
        if response.status_code != 200:
            raise ValueError(f"Failed to load program. Status code: {response.status_code}. Response: {response.text}")
        
    def start_program(self):
        # send a put request to http://192.168.1.207:8082/v2/status with the following body:
        # {
        #     "state": "Executing"
        # }
        # check the state before sending the request. The state must be IDLE.
        if self.get_state_and_message()[0] != MRAState.IDLE:
            raise ValueError(f"The MRA must be in IDLE state to start a program. Current state: {self.get_state_and_message()[0]}")
        response = requests.put(f"http://{self.ip}:8082/v2/status", json={"state": "Executing"})
        if response.status_code != 200:
            raise ValueError(f"Failed to start program. Status code: {response.status_code}. Response: {response.text}")
        
    def stop_program(self):
        # send a put request to http://192.168.1.207:8082/v2/status with the following body:
        # {
        #     "state": "Ready"
        # }
        response = requests.put(f"http://{self.ip}:8082/v2/status", json={"state": "Ready"})
        if response.status_code != 200:
            raise ValueError(f"Failed to stop program. Status code: {response.status_code}. Response: {response.text}")
        
    def load_main_program(self, target_base_position: str, robot_arm_program: str):
        # use self.load_program to load the robot_arm_program with the following arguments template:
        # arguments =[{"name": "target_base_position", "type": 0, "value": target_base_position}, 
        # {"name": "robot_arm_program", "type": 0, "value": robot_arm_program}]
        arguments = [{"name": "target_base_position", "type": 0, "value": target_base_position}, 
                     {"name": "robot_arm_program", "type": 0, "value": robot_arm_program}]
        self.load_program("Main", arguments)