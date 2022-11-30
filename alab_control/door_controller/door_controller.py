import time
from enum import Enum
import socket

from alab_control._base_arduino_device import BaseArduinoDevice


class DoorControllerState(Enum):
    RUNNING = "RUNNING"
    STOP = "STOP"
    ERROR = "ERROR"

class DoorController(BaseArduinoDevice):
    def __init__(self, ip_address: str, port: int = 8888, names: list = ["A", "B", "C", "D"]):
        super().__init__(ip_address, port)
        self.is_open = {}
        self.names=names
        for name in self.names:
            self.is_open[name]=False

    def send_request(self,data) -> str:
        clientSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM);
        # Connect to the server
        clientSocket.connect((self.ip_address,self.port));
        # Send data to server
        clientSocket.send(data.encode());
        # Receive data from server
        dataFromServer = clientSocket.recv(1024);
        # Print to the console
        decodedData=dataFromServer.decode()
        clientSocket.close()
        return decodedData

    def get_state(self) -> DoorControllerState:
        """
        Get the current state of the cap dispenser
        whether it is running or not.
        """
        try:
            state=self.send_request("Status\n").split(";")[0].split("State: ")[1]
        except:
            state="ERROR"
        return DoorControllerState[state]

    def open(self, name: str):
        """
        Open the Door with name
        """
        if name not in self.names:
            raise ValueError("name must be one of the specified names in the initialization"+str(self.names))
        if self.get_state() == DoorControllerState.RUNNING:
            raise RuntimeError("Cannot open the door while the door controller is running")
        if self.is_open[name]:
            raise RuntimeError("Cannot open the door while the door is open")
        self.send_request("Open "+name+"\n")
        time.sleep(1)
        while self.get_state() == DoorControllerState.RUNNING and self.get_state() != DoorControllerState.ERROR:
            time.sleep(1)
        if self.get_state() == DoorControllerState.ERROR:
            raise RuntimeError("Door Controller is in error state")
        else:
            self.is_open[name] = True

    def close(self, name: str):
        """
        Close the Door with name
        """
        if name not in self.names:
            raise ValueError("name must be one of the specified names in the initialization"+str(self.names))
        if self.get_state() == DoorControllerState.RUNNING:
            raise RuntimeError("Cannot close the door while the door controller is running")
        if not self.is_open[name]:
            raise RuntimeError("Cannot close the door while the door is closed")
        self.send_request("Close "+name+"\n")
        time.sleep(1)
        while self.get_state() == DoorControllerState.RUNNING and self.get_state() != DoorControllerState.ERROR:
            time.sleep(1)
        if self.get_state() == DoorControllerState.ERROR:
            raise RuntimeError("Door Controller is in error state")
        else:
            self.is_open[name] = False
