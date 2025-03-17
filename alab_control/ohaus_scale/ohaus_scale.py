import re
import socket
import time


class OhausScale:
    def __init__(self, ip: str, timeout: int = 3, max_retries: int = 10):
        self.ip = ip
        self.timeout = timeout
        self.max_retries = max_retries
        self.set_unit_to_mg()

    def send_command(self, command: str):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout)
            s.connect((self.ip, 9761))
            command += "\n"
            s.sendall(command.encode())
            response = s.recv(2048).decode(encoding="utf-8")
        return response

    def set_unit_to_mg(self):
        self.send_command("0U")

    def get_mass_in_mg(self):
        retry = 0
        mass_string = None
        while retry < self.max_retries:
            try:
                mass_string = self.send_command("SP").strip()
                break
            except socket.timeout:
                retry += 1
                time.sleep(0.5)
            except OSError:
                retry += 1
                time.sleep(0.5)
        if mass_string is None:
            raise TimeoutError("Failed to get mass from scale.")
        else:
            return int(re.search(r"\d+", mass_string).group())


if __name__ == "__main__":
    scale = OhausScale("192.168.0.24", timeout=0.1)
    print(scale.get_mass_in_mg())
    scale.close()
