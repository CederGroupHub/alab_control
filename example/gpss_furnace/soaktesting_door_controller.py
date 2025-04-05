import time

from alab_control._base_arduino_device import BaseArduinoDevice


class DoorController(BaseArduinoDevice):
    ALL_DOORS = ["A", "B"]

    def open_furnace(self, name: str, block: bool = True):
        if name not in self.ALL_DOORS:
            raise ValueError(
                f"Invalid door name: {name}. Must be one of {self.ALL_DOORS}"
            )
        endpoint = f"/open_{name.lower()}"

        status = self.get_status()
        if status[f"furnace{name}"] == "Open":
            return

        self.run_action(endpoint, block)

        # check if the door is open
        status = self.get_status()
        if status[f"furnace{name}"] != "Open":
            raise RuntimeError(
                f"Failed to open door {name}: {status.get('error', 'Unknown error')}. "
                f"Raw response: {status}"
            )

    def close_furnace(self, name: str, block: bool = True):
        if name not in self.ALL_DOORS:
            raise ValueError(
                f"Invalid door name: {name}. Must be one of {self.ALL_DOORS}"
            )
        endpoint = f"/close_{name.lower()}"
        self.run_action(endpoint, block)

        # check if the door is closed
        status = self.get_status()
        if status[f"furnace{name}"] != "Closed":
            raise RuntimeError(
                f"Failed to close door {name}: {status.get('error', 'Unknown error')}. "
                f"Raw response: {status}"
            )

    def run_action(self, endpoint: str, block: bool = True):
        """
        Run action on the furnace
        """
        response = self.send_request(endpoint, method="GET", timeout=10, max_retries=3)
        if not response["success"]:
            raise RuntimeError(
                f"Failed to run action {endpoint}: {response.get('error', 'Unknown error')}. "
                f"Raw response: {response}"
            )
        # ideally it should not end early. But if it does, something should be wrong
        time.sleep(1)
        status = self.get_status()
        start_time = time.time()

        # make sure it starts
        while (
            status["furnaceA"] != "Opening"
            and status["furnaceB"] != "Opening"
            and status["furnaceA"] != "Closing"
            and status["furnaceB"] != "Closing"
        ):
            time.sleep(0.1)
            status = self.get_status()
            if time.time() - start_time > 5:
                raise RuntimeError("Furnace status did not update in time")

        if block:
            while self.is_running():
                time.sleep(0.1)

    def get_status(self):
        """
        Get the status of the furnace
        """
        response = self.send_request(
            "/status", method="GET", timeout=10, max_retries=10
        )
        return response

    def is_running(self, raise_for_error: bool = True) -> bool:
        """
        Check if the furnace is running
        """
        response = self.get_status()
        if raise_for_error:
            if response["furnaceA"] == "Error":
                raise RuntimeError("Furnace A opening timeout")
            if response["furnaceB"] == "Error":
                raise RuntimeError("Furnace B opening timeout")

        return response["furnaceA"] in {"Closing", "Opening"} or response[
            "furnaceB"
        ] in {"Closing", "Opening"}


if __name__ == "__main__":
    furnace_door_controller = DoorController("192.168.1.88")

    for i in range(50):
        furnace_door_controller.open_furnace("A")
        furnace_door_controller.close_furnace("A")
        furnace_door_controller.open_furnace("B")
        furnace_door_controller.close_furnace("B")
