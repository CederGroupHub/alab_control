import time
from enum import Enum
import socket
import re

from alab_control._base_arduino_device import BaseArduinoDevice


class VacuumControllerState(Enum):
    RUNNING = "RUNNING"
    STOP = "STOP"
    ERROR = "ERROR"

class VacuumController(BaseArduinoDevice):
    def __init__(self, ip_address: str, port: int = 8888):
        super().__init__(ip_address, port)
        self.is_on = False

    def send_request(self,data,max_retries=10) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM,) as clientSocket:
            clientSocket.settimeout(10)
            try:
                clientSocket.connect((self.ip_address,self.port))
            except:
                # print( "re-connecting" )  
                connected=False
                retry=0
                while not connected and retry <= max_retries:
                    try:
                        retry+=1
                        clientSocket.connect((self.ip_address,self.port))
                        connected = True
                        # print( "re-connection successful" )  
                    except socket.error:  
                        time.sleep(1)
            # Send data to server
            clientSocket.send(data.encode());
            # Receive data from server
            dataFromServer = clientSocket.recv(1024);
            # print(dataFromServer)
            # Print to the console
            decodedData=dataFromServer.decode()
        return decodedData

    def get_state(self) -> VacuumControllerState:
        """
        Get the current state of the door controller
        whether it is running or not. Also updates self.is_open[name] for each name
        """
        try:
            reply=self.send_request("Status\n")
            state = reply.split(";")[0].split("State: ")[1]

            vacuum_state = re.findall(f"Equipment B: (\w*)", reply)
            if len(vacuum_state) == 0:
                raise ValueError("Could not find state for the vacuum")
            self.is_on = vacuum_state[0] == "On"
        except:
            state="ERROR"
        return VacuumControllerState[state]

    def on(self):
        """
        Turn on vacuum
        """
        if self.get_state() == VacuumControllerState.ERROR:
            raise RuntimeError("Vacuum Controller is in error state")
        if self.is_on:
            return
        self.send_request("Turn on Equipment B\n")
        time.sleep(1)
        while self.get_state() == VacuumControllerState.RUNNING and self.get_state() != VacuumControllerState.ERROR:
            time.sleep(1)
        if self.get_state() == VacuumControllerState.ERROR:
            raise RuntimeError("Vacuum Controller is in error state")

    def off(self):
        """
        Turn on vacuum
        """
        if self.get_state() == VacuumControllerState.ERROR:
            raise RuntimeError("Vacuum Controller is in error state")
        if not self.is_on:
            return
        self.send_request("Turn off Equipment B\n")
        time.sleep(1)
        while self.get_state() == VacuumControllerState.RUNNING and self.get_state() != VacuumControllerState.ERROR:
            time.sleep(1)
        if self.get_state() == VacuumControllerState.ERROR:
            raise RuntimeError("Vacuum Controller is in error state")
        