import time
from enum import Enum
import socket
import re

from alab_control._base_arduino_device import BaseArduinoDevice


class DoorControllerState(Enum):
    RUNNING = "RUNNING"
    STOP = "STOP"
    ERROR = "ERROR"

class DoorController(BaseArduinoDevice):
    def __init__(self, names: list, ip_address: str, port: int = 8888):
        super().__init__(ip_address, port)
        self.is_open = {
            name: False for name in names
        }
        self.names=names
        # self.get_state() #update door open status

    def send_request(self,data,max_retries=5) -> str:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM,) as clientSocket:
            clientSocket.settimeout(5)
            # Connect to the server
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
            # Print to the console
            decodedData=dataFromServer.decode()
        return decodedData

    def get_state(self) -> DoorControllerState:
        """
        Get the current state of the door controller
        whether it is running or not. Also updates self.is_open[name] for each name
        """
        try:
            reply=self.send_request("Status\n")
            state = reply.split(";")[0].split("State: ")[1]

            for name in self.names:
                door_state = re.findall(f"Furnace {name}: (\w*)", reply)
                if len(door_state) == 0:
                    raise ValueError("Could not find door state for door "+name)
                self.is_open[name] = door_state[0] == "Open"
        except:
            state="ERROR"
        return DoorControllerState[state]

    def open(self, name: str):
        """
        Open the Door with name
        """
        if name not in self.names:
            raise ValueError("name must be one of the specified names in the initialization"+str(self.names))
        state = self.get_state()
        if self.get_state() == DoorControllerState.ERROR:
            raise RuntimeError("Door Controller is in error state")
        if self.is_open[name]:
            return
        if state == DoorControllerState.RUNNING:
            raise RuntimeError("Cannot open the door while the door controller is running")
        
        self.send_request("Open "+name+"\n")
        time.sleep(1)
        while self.get_state() == DoorControllerState.RUNNING and self.get_state() != DoorControllerState.ERROR:
            time.sleep(1)
        if self.get_state() == DoorControllerState.ERROR:
            raise RuntimeError("Door Controller is in error state")
        


    def close(self, name: str):
        """
        Close the Door with name
        """
        if name not in self.names:
            raise ValueError("name must be one of the specified names in the initialization"+str(self.names))
        state = self.get_state()
        if self.get_state() == DoorControllerState.ERROR:
            raise RuntimeError("Door Controller is in error state")
        if not self.is_open[name]:
            return
        if state == DoorControllerState.RUNNING:
            raise RuntimeError("Cannot open the door while the door controller is running")
        
        self.send_request("Close "+name+"\n")
        time.sleep(1)
        while self.get_state() == DoorControllerState.RUNNING and self.get_state() != DoorControllerState.ERROR:
            time.sleep(1)
        if self.get_state() == DoorControllerState.ERROR:
            raise RuntimeError("Door Controller is in error state")
        