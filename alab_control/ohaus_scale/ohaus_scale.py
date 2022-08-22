import re
import socket


class OhausScale:
    def __init__(self, ip: str, timeout: int = 2):
        self.ip = ip
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        self._socket.connect((ip, 9761))
        self.set_unit_to_mg()

    def send_command(self, command: str):
        command += "\n"
        self._socket.sendall(command.encode())
        response = self._socket.recv(2048).decode(encoding="utf-8")
        return response

    def close(self):
        self._socket.close()

    def set_unit_to_mg(self):
        self.send_command("0U")

    def get_mass_in_mg(self):
        mass_string = self.send_command("SP").strip()
        return int(re.search(r"\d+", mass_string).group())


if __name__ == "__main__":
    scale = OhausScale("192.168.0.24")
    print(scale.get_mass_in_mg())
    scale.close()
