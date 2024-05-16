import re
import numpy as np
import xmltodict
import socket
import time
import os
from typing import List, Tuple, Union, Dict
from enum import Enum

### Exceptions
class AerisException(Exception):
    """Generic exception class for Aeris errors"""

    pass


class ScanFailed(AerisException):
    """Scan failed for some reason"""

    pass


class Aeris:
    ALL_SLOTS: Dict[Union[str, int], int] = {
        # "inside": 0,
        # 0: 0,
        "belt": 1,
        1: 2,
        2: 3,
        3: 4,
        4: 5,
        5: 6,
    }  # key of slot locations -> aeris slot indices
    ALLOWED_SLOTS = {
        1: 2,
        # 2: 3,
        # 3: 4,
    }  # slot locations that are allowed for ALab samples
    COMMUNICATION_DELAY: float = 0.2  # time to wait between sending a message to Aeris and searching for a response
    FILEWRITE_TIMEOUT: float = 10  # seconds to wait after trying to read a file before considering it a failure

    # Replace IP, port, and directory paths with your own info
    def __init__(
        self,
        ip: str,
        results_dir: str,
        debug: bool = False,
    ):
        self.ip = ip
        self.port = 702
        self.results_dir = results_dir
        self._debug = debug  # if true, prints all communication to Aeris

    @property
    def xrd_is_busy(self) -> bool:
        """Check if the Aeris is currently taking an XRD measurement

        Returns:
            bool: True = diffractometer is busy, False = idle
        """
        msg = f"@STATUS_REQUEST@UNIT=xrd@END"
        reply = self._query(msg)
        hits = re.findall("READY=(\w*)", reply)
        if len(hits) == 0:
            raise AerisException("Could not determine if Aeris is busy!")
        if hits[0] == "yes":
            return False
        return True

    @property
    def is_under_remote_control(self) -> bool:
        """Check if the Aeris is currently under remote control

        Returns:
            bool: True = under remote control, False = not under remote control
        """
        msg = f"@STATUS_REQUEST@SYSTEM@END"
        reply = self._query(msg)
        hits = re.findall("SYSTEM=(\w*)", reply)
        if len(hits) == 0:
            raise AerisException(
                "Could not determine if Aeris is under remote control!"
            )
        return hits[0] == "remote"

    def __get_slot(
        self, loc: Union[str, int], limit_to_allowed_slots: bool = True
    ) -> int:
        """Return Aeris slot number for given location

        Args:
            loc (Union[str,int]): Index or string alias for slot
            limit_to_allowed_slots (bool, optional): If True, only return slots that are allowed for ALab samples. if False, return all Aeris slots. Defaults to True.

        Returns:
            int: internal index of slot for communication to Aeris
        """
        if limit_to_allowed_slots:
            slotkey = self.ALLOWED_SLOTS
        else:
            slotkey = self.ALL_SLOTS
        if loc not in slotkey:
            raise ValueError(
                f"Invalid slot location! Valid locations are: {slotkey.keys()}"
            )
        return slotkey[loc]

    def _query(self, msg: str) -> str:
        """Send a message to the Aeris, return the reply

        Args:
            msg (str): message to send to Aeris

        Returns:
            str: Aeris reply
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.ip, self.port))
            if self._debug:
                print("sent: ", msg)
            msg_bytes = bytes(msg, encoding="utf-8")
            s.sendall(msg_bytes)
            data = s.recv(1024)
            if self._debug:
                print("recv: ", repr(data))
            time.sleep(
                self.COMMUNICATION_DELAY
            )  # TODO do we actually need this here? seems unlikely

        return str(data)

    def is_slot_empty(self, loc: Union[str, int]) -> bool:
        """Check if a given slot is empty. This checks the Aeris' proximity sensor results (ie checks if a sample is physically present in the slot, regardless of whether a sample has been added to the Aeris database at this slot)

        Args:
            loc (Union[str,int]): Index or alias for slot

        Returns:
            bool: True if slot is empty, False otherwise
        """
        slot_index = self.__get_slot(loc, limit_to_allowed_slots=False)
        data = self._query(f"@STATUS_REQUEST@LOCATION=0,{slot_index}@END")
        for output in str(data).split("@"):
            if "STATE" in output:
                status = output.split("=")[1]

        if status == "free":
            return True
        elif status == "occupied":
            return False
        else:
            raise AerisException(
                "Could not determine if slot {loc} is empty -- Aeris returned {status}!"
            )

    def scan(
        self,
        sample_id: str,
        program: str = "10-140_2-min",
    ):
        """perform an XRD measurement using an existing program

        Args:
            sample_id (str, optional): sample_id that Aeris should assign to this scan. Defaults to "unknown_sample".
            program (str, optional): Scan program that the Aeris should use to acquire data. This must be created beforehand. Defaults to "10-140_2-min".

        Raises:
            ScanFailed: Scan failed for some reason
        """
        # slot_index = self.__get_slot(loc)

        msg = f"@SAMPLE@MEASURE@SAMPLE_ID={sample_id}@APPLICATION={program}@END"
        reply = self._query(msg)
        print(f"{self.get_current_time()} Starting XRD scan for sample {sample_id} using program {program}")
        if "fatal" in reply:
            raise ScanFailed(
                f"Scan failed for program {program} on sample_id {sample_id}! Aeris returned: {reply}"
            )

    def load_scan_results(self, sample_id: str) -> Tuple[np.array, np.array]:
        """Load scan results from Aeris

        Args:
            sample_id (str): sample_id given to Aeris during scan

        Returns:
            Tuple[np.array, np.array]: arrays of 2theta and intensity values
        """
        filename = f"{sample_id}.xrdml"
        t_start = time.time()
        while filename not in os.listdir(self.results_dir):
            if (time.time() - t_start) > self.FILEWRITE_TIMEOUT:
                raise ScanFailed(f"Scan results for {sample_id} not found!")
            time.sleep(self.FILEWRITE_TIMEOUT / 10)

        with open(os.path.join(self.results_dir, filename), "r", encoding="utf-8") as f:
            xrd_dict = xmltodict.parse(f.read())
            min_angle = float(
                xrd_dict["xrdMeasurements"]["xrdMeasurement"]["scan"]["dataPoints"][
                    "positions"
                ][0]["startPosition"]
            )
            max_angle = float(
                xrd_dict["xrdMeasurements"]["xrdMeasurement"]["scan"]["dataPoints"][
                    "positions"
                ][0]["endPosition"]
            )

            intensities = xrd_dict["xrdMeasurements"]["xrdMeasurement"]["scan"][
                "dataPoints"
            ]["counts"]["#text"]
            intensities = np.array([float(val) for val in intensities.split()])
            angles = np.linspace(min_angle, max_angle, len(intensities))
        print(f"{self.get_current_time()} Scan results for {sample_id} loaded successfully")

        return angles, intensities

    def scan_and_return_results(
        self, sample_id: str, program: str = "10-140_2-min"
    ) -> Tuple[np.array, np.array]:
        """Perform an XRD scan and return the results. Blocks until results are available.

        Args:
            sample_id (str): sample_id that Aeris should assign to this scan
            program (str, optional): Scan program that the Aeris should use to acquire data. This must be created beforehand. Defaults to "10-140_2-min".

        Returns:
            Tuple[np.array, np.array]: arrays of 2theta and intensity values
        """
        self.scan(sample_id, program)
        time.sleep(10) #wait for the sample to be loaded and the scan to start
        while self.xrd_is_busy:
            time.sleep(2)
        time.sleep(5)  # wait for the gripper to fully stop
        return self.load_scan_results(sample_id)

    def add(
        self,
        sample_id: str,
        loc: Union[str, int],
        default_program: str = "10-140_2-min",
    ):
        """Add a sample to the Aeris' memory. This should be run when physically loading a sample onto the instrument.

        Args:
            sample_id (str): sample_id to associate with this sample within the Aeris' memory
            loc (Union[str, int]): Index or alias for slot sample is physically being loaded into
        """
        slot_index = self.__get_slot(loc)
        msg = f"@SAMPLE@ADD@APPLICATION={default_program}@SAMPLE_ID={sample_id}@AT=0,{slot_index}@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise AerisException(f"Could not add sample {sample_id} to location {loc}! Aeris returned: {reply}")

    def remove(self, sample_id: str):
        """Removes a sample from the Aeris' memory. This is necessary once the sample is physically removed from the instrument.

        Args:
            sample_id (str): sample_id within the Aeris
        """
        msg = f"@SAMPLE@REMOVE@SAMPLE_ID={sample_id}@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise AerisException(
                f"Could not remove sample_id {sample_id} from the Aeris' memory. Aeris returned: {reply}"
            )

    def remove_by_slot(self, loc: Union[str, int]):
        """Removes a sample from the Aeris' memory. This is necessary once the sample is physically removed from the instrument.

        Args:
            loc (Union[str, int]): Index or alias for slot sample is physically being loaded into
        """
        slot_index = self.__get_slot(loc, limit_to_allowed_slots=False)
        msg = f"@SAMPLE@REMOVE@SAMPLE_ID@AT=0,{slot_index}@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise AerisException(
                f"Could not remove sample from location {loc} from the Aeris' memory. Aeris returned: {reply}"
            )

    def move(
        self,
        initial_loc: Union[str, int],
        target_loc: Union[str, int],
    ):
        """Move a sample from one location to another

        Args:
            initial_loc (Union[str,int]): Index or alias for slot to move sample from
            target_loc (Union[str,int]): Index or alias for slot to move sample to

        Raises:
            AerisException: _description_
        """
        initial_slot = self.__get_slot(initial_loc, limit_to_allowed_slots=False)
        target_slot = self.__get_slot(target_loc, limit_to_allowed_slots=False)

        # msg = f"@SAMPLE@MOVE@SAMPLE_ID={sample_id}@AT=0,{initial_slot}@TO=0,{target_slot}@END"
        msg = f"@SAMPLE@MOVE@SAMPLE_ID@AT=0,{initial_slot}@TO=0,{target_slot}@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise AerisException(
                f"Failed to move sample from location {initial_loc} to location {target_loc}! Aeris returned: {reply}"
            )

    def move_arm_out_of_the_way(self):
        self.move(5, 4)

    def get_current_time(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


# Write XRD data to file
def write_spectrum(dir, sample_id, angles, intensities):
    filepath = os.path.join(dir, "%s.xy" % sample_id)
    with open(filepath, "w+") as spec_file:
        for x, y in zip(angles, intensities):
            spec_file.write("%s %s\n" % (x, y))


if __name__ == "__main__":
    a = Aeris(debug=True)
    print(a.add("test_remote", loc=1, default_program="10-100_8-minutes"))
    print(a.scan_and_return_results("test_remote", program="10-60_2-min"))
    print(a.remove("test_remote"))
