"""
A base device abstraction for all the aduino devices that have RESTful API endpoints
"""
import abc
import time
from typing import Dict, Union, Optional

import requests


class BaseArduinoDevice(abc.ABC):
    def __init__(self, ip_address: str, port: int = 80):
        self.ip_address = ip_address
        self.port = port

    def send_request(self, endpoint: str, data: Optional[Dict[str, Union[str, int, float, bytes, bool]]] = None,
                     method: str = "GET", jsonify: bool = True, suppress_error: bool = False):
        url = f"http://{self.ip_address}:{self.port}{endpoint}"
        time.sleep(0.1)
        response = requests.request(method=method, url=url, data=data)
        if not suppress_error:
            response.raise_for_status()
        if jsonify:
            return response.json()
        return response
