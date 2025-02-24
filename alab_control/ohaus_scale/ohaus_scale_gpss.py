import re
import socket


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

    def get_mass_in_mg(self, get_command: str = "SP"):
        # SP: Stable Print (Print mass after value stabilizes)
        # IP: Immediate Print (Print mass regardless of value stabilizes)
        retry = 0
        mass_string = None
        while retry < self.max_retries:
            try:
                mass_string = self.send_command(get_command).strip()
                break
            except socket.timeout:
                retry += 1
        if mass_string is None:
            return None
        else:
            return int(re.search(r"\d+", mass_string).group())
        
if __name__ == "__main__":
    scale = OhausScale("ohaus.gpss", timeout=0.1)
    print(scale.get_mass_in_mg())
    scale.close()
