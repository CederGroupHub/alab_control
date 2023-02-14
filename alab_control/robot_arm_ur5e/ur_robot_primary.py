"""
#UR Controller Client Interface Datastream Reader
# For software version 3.x
#
# Datastream info found here: https://s3-eu-west-1.amazonaws.com/ur-support-site/16496/Client_Interface.xlsx
# Struct library used to extract data, info found here: https://docs.python.org/2/library/struct.html
"""

import socket
import time
from contextlib import contextmanager
from threading import Lock, Thread, Event
from typing import Dict, Any, Optional

from urx.ursecmon import ParserUtils, ParsingException


class URRobotPrimary:
    def __init__(self, ip: str, timeout: float = 5):
        """
        The primary interface (30011, read-only) to UR Robot

        This is used to monitor the popup in the robot arm.

        Args:
            ip: the ip address to the UR Robot
            timeout: timeout time in sec
        """
        # set up socket connection
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        self._socket.connect((ip, 30011))
        time.sleep(0.1)
        self._socket.recv(4096)

        self._parser = ParserUtils()

        self._thread = None
        self._mutex_lock = Lock()

        self._stop_event = Event()

        self._popup_title: Optional[str] = None
        self._popup_message: Optional[str] = None

    def close(self):
        self._socket.close()

    def read_data(self) -> Dict[str, Any]:
        self._mutex_lock.acquire()

        try:
            data = self._socket.recv(4096)
            try:
                data = self._parser.parse(data)
            except ParsingException:
                return {}
            return data
        except:
            return {}
        finally:
            self._mutex_lock.release()

    def read_popup(self):
        data = self.read_data()
        if "popupMessage" in data:
            return {
                "title": data["popupMessage"]["messageTitle"].decode("utf-8"),
                "message": data["popupMessage"]["messageText"].decode("utf-8"),
            }
        return None

    def keep_monitoring_popup(self):
        while True:
            if not self._stop_event.is_set():
                popup = self.read_popup()
                if popup is not None:
                    self._popup_message = popup["message"]
                    self._popup_title = popup["title"]
            else:
                break
            time.sleep(0.1)

    @contextmanager
    def monitor_popup(self):
        need_release = False
        try:
            if self._thread is None:
                self._thread = Thread(target=self.keep_monitoring_popup)
                self._thread.start()
                need_release = True
            yield self
        finally:
            if need_release:
                self._stop_event.set()
                self._thread.join()
                self._thread = None
                self._stop_event.clear()
                self.clear_popup_cache()

    @property
    def popup_title(self) -> Optional[str]:
        return self._popup_title

    @property
    def popup_message(self) -> Optional[str]:
        return self._popup_message

    def clear_popup_cache(self):
        """
        Clear the cache of popup message and title

        It should be used with the close popup
        """
        self._popup_title = None
        self._popup_message = None
