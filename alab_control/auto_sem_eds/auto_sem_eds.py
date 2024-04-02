from enum import Enum
import PyPhenom as ppi

from alab_control._base_sem_device import PhenomDevice

class SEMState(Enum):
    """Enumeration of SEM states."""
    IDLE = "idle"
    SCANNING = "scanning"
    ERROR = "error"

class SEMDevice(PhenomDevice):
    """
    Class for controlling a Scanning Electron Microscope (SEM).
    """

    def __init__(self, device_name, connection_params, license_details):
        super().__init__(device_name, connection_params, license_details)
        self.phenom = ppi.Phenom()

    ENDPOINTS = {
        "start_scan": "/start_scan",
        "stop_scan": "/stop_scan",
        "state": "/state",
        "set_magnification": "/set_magnification",
    }

    def connect(self):
        """
        Establish a connection to the SEM. Override the base class's connect method.
        """
        # Implementation details depend on how the SEM is connected (e.g., via serial port, network, etc.)
        super().connect()  # Call the base class connect method
        self.is_connected = True

    def get_state(self) -> SEMState:
        """
        Retrieves the current state of the SEM.
        """
        return SEMState.IDLE
    
    def start_scan(self):
        """Starts a scanning session on the SEM."""
        if self.get_state() == SEMState.SCANNING:
            raise RuntimeError("SEM is already scanning")
        self.send_request(self.ENDPOINTS["start_scan"], method="POST")

    def stop_scan(self):
        """Stops the scanning session."""
        self.send_request(self.ENDPOINTS["stop_scan"], method="POST")

    def set_magnification(self, level: int):
        """Sets the magnification level for the SEM."""
        self.send_request(self.ENDPOINTS["set_magnification"], data={"level": level}, method="POST")

    def get_state(self) -> SEMState:
        """Retrieves the current state of the SEM."""
        state = self.send_request(self.ENDPOINTS["state"], method="GET")["state"].upper()
        return SEMState[state]

    def send_request(self, endpoint, data=None, method="GET"):
        """
        Send a request to the SEM. Specific implementation of the base class's placeholder method.
        """
        # This method would wrap the PyPhenom library calls to control the SEM, depending on the 'endpoint'.
        pass  #TODO


