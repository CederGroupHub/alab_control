import time
from enum import Enum

import requests

class MRAState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    SAFEGUARD_STOP = "safeguard_stop"

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
            return MRAState.IDLE, response["message"]
        elif state == "Executing":
            return MRAState.RUNNING, response["message"]
        elif state == "Execution Error Active":
            return MRAState.ERROR, response["message"]
        elif state == "Finishing Execution":
            return MRAState.RUNNING, response["message"]
        elif state == "Emergency Stop Active":
            return MRAState.ERROR, response["message"]
        elif state == "Safeguard Stop Active":
            return MRAState.SAFEGUARD_STOP, response["message"]
        else:
            return MRAState.ERROR, f"Unknown state: {state}. Please check the API documentation for the full list of states."
        
    def acknowledge_error(self):
        # send a put request to http://192.168.1.207:8082/v2/status with the following body:
        # {
        #     "state": "Ready"
        # }
        time.sleep(5) # wait for 5 seconds to make sure the MRA is ready to acknowledge the error
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
            # if status code is 400 and response contains "ActivateProgramming", try again after acknowledging the error
            if response.status_code == 400 and "ActivateProgramming" in response.text:
                try:
                    self.acknowledge_error()
                except Exception as e:
                    pass
                finally:
                    time.sleep(5) # wait for 5 seconds to make sure the MRA is ready to load the program
                    self.load_program(program_name, arguments)
                    return
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
        
    def load_main_program(self, target_base_position: str, source_region: str, source_slot: str, destination_region: str, destination_slot: str):
        # use self.load_program to load the robot_arm_program with the following arguments template:
        # arguments =[{"name": "target_base_position", "type": 0, "value": target_base_position}, 
        # {"name": "robot_arm_job", "type": 0, "value": robot_arm_job},
        # {"name": "robot_arm_region", "type": 0, "value": robot_arm_region},
        # {"name": "robot_arm_slot", "type": 0, "value": robot_arm_slot}]
        arguments = [{"name": "target_base_position", "type": 0, "value": target_base_position}, 
                     {"name": "source_region", "type": 0, "value": source_region},
                     {"name": "source_slot", "type": 0, "value": source_slot},
                     {"name": "destination_region", "type": 0, "value": destination_region},
                     {"name": "destination_slot", "type": 0, "value": destination_slot}]
        self.load_program("Main", arguments)

    def is_running(self) -> bool:
        """
        Return True if the MRA is running.
        """
        # if the state is SAFEGUARD_STOP, wait for 10 seconds and try check again, try 3 times
        self.state, self.message = self.get_state_and_message()
        if self.state == MRAState.SAFEGUARD_STOP:
            for _ in range(3):
                time.sleep(10)
                self.state, self.message = self.get_state_and_message()
                if self.state != MRAState.SAFEGUARD_STOP:
                    break
        return self.state == MRAState.RUNNING
    
    def is_error(self) -> bool:
        """
        Return True if the MRA is in error state.
        """
        return self.get_state_and_message()[0] == MRAState.ERROR

    def wait_for_program_to_finish(self):
        # wait for the program to finish.
        while self.is_running():
            time.sleep(1)
        self.state, self.message = self.get_state_and_message()
        # if the state is SAFEGUARD_STOP, wait for 10 seconds and try check again, try 3 times
        if self.state == MRAState.SAFEGUARD_STOP:
            for _ in range(3):
                time.sleep(10)
                self.state, self.message = self.get_state_and_message()
                if self.state != MRAState.SAFEGUARD_STOP:
                    break
            if self.state == MRAState.SAFEGUARD_STOP:
                raise ValueError(f"Program finished with safeguard stop. Message: {self.message}")
        # if the state is ERROR, raise an error
        if self.state == MRAState.ERROR:
            raise ValueError(f"Program finished with error. Message: {self.message}")
        elif self.state == MRAState.IDLE:
            pass
        else:
            raise ValueError(f"Unknown state: {self.state}. Please check the API documentation for the full list of states.")
        
    def run_main_program(self, target_base_position: str, source_region: str, source_slot: str, destination_region: str, destination_slot: str):
        # load the main program
        self.load_main_program(target_base_position, source_region, source_slot, destination_region, destination_slot)
        time.sleep(2) # wait for the program to load.
        # start the program
        self.start_program()
        time.sleep(2) # wait for the program to start.
        # wait for the program to finish
        self.wait_for_program_to_finish()
    
    def charge(self):
        self.run_main_program("Charging", "None", "None", "None", "None")

    def charge_no_waiting(self):
        self.run_main_program("ChargingNoWait", "None", "None", "None", "None")