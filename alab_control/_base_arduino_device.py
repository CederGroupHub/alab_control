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
        # One session per device. requests.request() opens and closes a TCP
        # connection every call; after a while Windows will not allow another
        # connection to that board until those sockets time out.
        self._http = requests.Session()
        self._http.headers["Connection"] = "keep-alive"

    def _reset_http(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass
        self._http = requests.Session()
        self._http.headers["Connection"] = "keep-alive"

    def send_request(self, endpoint: str, data: Optional[Dict[str, Union[str, int, float, bytes, bool]]] = None,
                     method: str = "GET", jsonify: bool = True, suppress_error: bool = False, timeout=600, max_retries=1, params: Optional[Dict[str, Union[str, int, float, bytes, bool]]] = None) -> Union[requests.Response, Dict]:
        """Send a request on this device's persistent HTTP connection."""
        url = f"http://{self.ip_address}:{self.port}{endpoint}"
        retries = 0
        while True:
            try:
                response = self._http.request(
                    method=method, url=url, data=data, timeout=timeout, params=params
                )
                break
            except Exception:
                retries += 1
                self._reset_http()
                if retries >= max_retries:
                    raise RuntimeError(f"Failed to send request to {url}")
                time.sleep(0.1)
        if not suppress_error:
            response.raise_for_status()
        if jsonify:
            try:
                return response.json()
            finally:
                response.close()
        return response
    
    def get_current_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
