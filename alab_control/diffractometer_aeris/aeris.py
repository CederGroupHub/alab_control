import numpy as np
import xmltodict
import socket
import time
import os
from typing import List, Tuple, Union, Dict
from enum import Enum

### Enumerations
class SlotStatus(Enum):
    UNKNOWN = "unknown"
    FREE = "free"
    OCCUPIED = "occupied"


class CommandResult(Enum):
    SUCCESS = "normal"
    ERROR = "fatal"


### Exceptions
class AerisException(Exception):
    """Generic exception class for Aeris errors"""

    pass


class ScanFailed(AerisException):
    """Scan failed for some reason"""

    pass


class Aeris:
    SLOTS: Dict[Union[str, int], int] = {
        "inside": 0,
        0: 0,
        1: 1,
        2: 2,
        3: 3,
        4: 4,
        5: 5,
    }  # key of slot locations -> aeris slot indices
    COMMUNICATION_DELAY: float = 5  # time to wait between sending a message to Aeris and searching for a response

    # Replace IP, port, and directory paths with your own info
    def __init__(
        self,
        ip: str = "10.0.0.188",
        port: int = 702,
        results_dir: str = "/Users/Cederexp/Documents/SharedFolder",
        working_dir: str = "./Results",
    ):
        self.ip = ip
        self.port = port
        self.results_dir = results_dir
        self.working_dir = working_dir

    def __get_slot(self, loc: Union[str, int]) -> int:
        """Return Aeris slot number for given location

        Args:
            loc (Union[str,int]): Index or string alias for slot

        Returns:
            int: internal index of slot for communication to Aeris
        """
        if loc not in self.SLOTS:
            raise ValueError(
                f"Invalid slot location! Valid locations are: {self.SLOTS.keys()}"
            )

    def _query(self, msg: str) -> str:
        """Send a message to the Aeris, return the reply

        Args:
            msg (str): message to send to Aeris

        Returns:
            str: Aeris reply
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.ip, self.port))
            msg_bytes = bytes(msg, encoding="utf-8")
            s.sendall(msg_bytes)
            data = s.recv(1024)
            time.sleep(
                self.COMMUNICATION_DELAY
            )  # TODO do we actually need this here? seems unlikely

        return str(data)

    def slot_status(self, loc: Union[str, int]) -> SlotStatus:
        """Check occupancy status of a given slot

        Args:
            loc (Union[str,int]): Index or alias for slot

        Returns:
            SlotStatus: Current occupancy status of slot
        """

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.ip, self.port))
            mssg = bytes("@STATUS_REQUEST@LOCATION=0,%s@END" % loc, encoding="utf-8")
            s.sendall(mssg)
            data = s.recv(1024)
            print(repr(data))
            time.sleep(5)
            for output in str(data).split("@"):
                if "STATE" in output:
                    status = output.split("=")[1]
            return status

    def scan(
        self,
        loc: Union[str, int],
        sample_id: str = "unknown_sample",
        program: str = "10-140_2-min",
    ) -> Tuple[np.array, np.array]:
        """perform an XRD measurement using an existing program

        Args:
            loc (Union[str,int]): Index or alias for slot containing sample
            sample_id (str, optional): sample_id that Aeris should assign to this scan. Defaults to "unknown_sample".
            program (str, optional): Scan program that the Aeris should use to acquire data. This must be created beforehand. Defaults to "10-140_2-min".

        Raises:
            ScanFailed: Scan failed for some reason

        Returns:
            Tuple(np.array, np.array): angles and intensities of scan
        """
        slot_index = self.__get_slot(loc)

        msg = f"@SAMPLE@ADD@SAMPLE_ID={sample_id}@APPLICATION={program}@AT=0,{slot_index}@MEASURE=yes@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise ScanFailed(
                f"Scan failed for program {program} on sample_id {sample_id} in location {loc}!"
            )

        angles, intensities = self.load_scan_results(sample_id)
        return angles, intensities

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
            time.sleep(1)
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

        return angles, intensities

    def add_to_aeris(self, sample_id: str, loc: Union[str, int]):
        """Add a sample to the Aeris' memory. This should be run when physically loading a sample onto the instrument.

        Args:
            sample_id (str): sample_id to associate with this sample within the Aeris' memory
            loc (Union[str, int]): Index or alias for slot sample is physically being loaded into
        """
        slot_index = self.__get_slot(loc)
        msg = f"@SAMPLE@ADD@SAMPLE_ID={sample_id}@AT=0,{slot_index}@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise AerisException(f"Could not add sample {sample_id} to location {loc}!")

    def remove_from_aeris(self, sample_id: str):
        """Removes a sample from the Aeris' memory. This is necessary once the sample is physically removed from the instrument.

        Args:
            sample_id (str): sample_id within the Aeris
        """
        msg = f"@SAMPLE@REMOVE@SAMPLE_ID={sample_id}@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise AerisException(
                f"Could not remove sample_id {sample_id} from the Aeris' memory"
            )

    def move(
        self,
        initial_loc: Union[str, int],
        target_loc: Union[str, int],
        sample_id: str = "unknown_sample",
    ):
        """Move a sample from one location to another

        Args:
            initial_loc (Union[str,int]): Index or alias for slot to move sample from
            target_loc (Union[str,int]): Index or alias for slot to move sample to
            sample_id (str, optional): Name of the sample. Defaults to "unknown_sample".

        Raises:
            AerisException: _description_
        """
        initial_slot = self.__get_slot(initial_loc)
        target_slot = self.__get_slot(target_loc)

        msg = f"@SAMPLE@MOVE@SAMPLE_ID={sample_id}@AT=0,{initial_slot}@TO=0,{target_slot}@END"
        reply = self._query(msg)
        if "fatal" in reply:
            raise AerisException(
                f"Failed to move sample_id {sample_id} from location {initial_loc} to location {target_loc}!"
            )


# # Write XRD data to file
# def write_spectrum(dir, sample_id, angles, intensities):
#     filepath = os.path.join(dir, "%s.xy" % sample_id)
#     with open(filepath, "w+") as spec_file:
#         for x, y in zip(angles, intensities):
#             spec_file.write("%s %s\n" % (x, y))
