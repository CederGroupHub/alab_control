import time

from alab_control._base_arduino_device import BaseArduinoDevice


class BalanceRestarter(BaseArduinoDevice):
    def restart_balance(self, block: bool = True):
        end_point = "/restart"
        if self.is_restart_in_progress():
            raise RuntimeError("Restart already in progress")

        response = self.send_request(end_point, method="GET", timeout=10, max_retries=3)
        if response["status"] != "ok":
            raise RuntimeError(
                f"Failed to restart balance: {response.get('message', 'Unknown error')}. "
                f"Raw response: {response}"
            )

        if block:
            while self.is_restart_in_progress():
                time.sleep(0.5)

    def get_status(self):
        end_point = "/status"
        response = self.send_request(end_point, method="GET", timeout=5, max_retries=10)
        return response

    def is_restart_in_progress(self):
        status = self.get_status()
        return status.get("restartInProgress", False)
