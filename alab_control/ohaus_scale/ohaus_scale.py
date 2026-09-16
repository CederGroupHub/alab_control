import logging

logger = logging.getLogger(__name__)
import re
import socket
import time

# Matches a weight value followed by a recognised unit in Ohaus output.
# Works on the standard "New Scout" print format and tolerates GLP headers
# (date/time, Balance ID, …) that the balance may prepend.
_WEIGHT_RE = re.compile(r"(-?\d+\.?\d*)\s+(mg|g|kg|ct|oz|lb)\b", re.IGNORECASE)

_UNIT_TO_MG = {
    "mg": 1,
    "g": 1_000,
    "kg": 1_000_000,
    "ct": 200,
    "oz": 28_349.5,
    "lb": 453_592,
}


class OhausScale:
    def __init__(self, ip: str, timeout: int = 3, max_retries: int = 10):
        self.ip = ip
        self.timeout = timeout
        self.max_retries = max_retries
        self.set_unit_to_mg()

    def send_command(self, command: str):
        """Send a single command to the balance and return the response.

        Opens a fresh TCP connection for each call.  Stale data left in the
        Ethernet kit's buffer by a previous session is drained before the
        command is sent, and responses are decoded as Latin-1 (the balance may
        return bytes outside the ASCII range after a factory reset).
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout)
            s.connect((self.ip, 9761))
            # Drain stale data the Ethernet kit may have buffered from an
            # earlier TCP session (common after rapid reconnects or when GLP
            # headers overflow the previous recv).
            s.settimeout(0.15)
            try:
                s.recv(4096)
            except socket.timeout:
                pass
            s.settimeout(self.timeout)
            s.sendall((command + "\n").encode())
            response = s.recv(4096).decode(encoding="latin-1")
        return response

    def set_unit_to_mg(self):
        self.send_command("0U")

    def tare(self):
        """Tare (zero) the scale at its current load.

        After taring, ``get_mass_in_mg`` reports the change in mass relative to the load that was
        present when this was called (so removing mass reads negative).
        """
        retry = 0
        while retry < self.max_retries:
            try:
                self.send_command("T")
                # give the balance a moment to settle on the new zero point
                time.sleep(1)
                return
            except (socket.timeout, OSError, TimeoutError):
                retry += 1
                time.sleep(0.5)
        raise TimeoutError("Failed to tare the scale.")

    @staticmethod
    def _parse_mass_mg(response):
        """Extract mass in milligrams from a potentially multi-line response.

        The balance may prepend GLP headers (date, Balance ID, user name, …)
        before the actual weight line.  This method searches every line for the
        first occurrence of ``<number> <unit>`` and converts to milligrams.

        Returns ``None`` when no weight line is found.
        """
        for line in response.splitlines():
            m = _WEIGHT_RE.search(line)
            if m:
                value = float(m.group(1))
                unit = m.group(2).lower()
                factor = _UNIT_TO_MG.get(unit, 1)
                return int(round(value * factor))
        return None

    def get_mass_in_mg(self):
        retry = 0
        mass_string = None
        while retry < self.max_retries:
            try:
                mass_string = self.send_command("SP").strip()
                if mass_string == "":
                    raise TimeoutError("No response from scale.")
                break
            except socket.timeout:
                retry += 1
                time.sleep(0.5)
            except (OSError, TimeoutError):
                retry += 1
                time.sleep(0.5)
        if mass_string is None:
            raise TimeoutError("Failed to get mass from scale.")

        # Structured parse — handles GLP headers, different units, decimal values
        mass = self._parse_mass_mg(mass_string)
        if mass is not None:
            return mass

        # Fallback: original integer-only regex (works when the balance is
        # already set to mg and the response is a single clean line).
        match = re.search(r"-?\d+", mass_string)
        if match is None:
            raise TimeoutError(
                f"Could not parse mass from scale response: {mass_string!r}"
            )
        return int(match.group())


if __name__ == "__main__":
    scale = OhausScale("192.168.0.24", timeout=0.1)
    logger.info(scale.get_mass_in_mg())
    scale.close()
