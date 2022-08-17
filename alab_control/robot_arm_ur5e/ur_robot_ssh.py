from pathlib import Path

import paramiko


class URRobotSSH:
    def __init__(self, ip: str):
        self.ip = ip
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(self.ip, username="root", password="easybot")

    def read_program(self, file_name: str, base: str = "/programs") -> str:
        with self._ssh.open_sftp() as sftp:
            with sftp.open((Path(base) / file_name).as_posix(), "r") as f:
                return f.read().decode("utf-8")

    def close(self):
        self._ssh.close()


if __name__ == '__main__':
    ur_robot_ssh = URRobotSSH("192.168.0.22")
    print(ur_robot_ssh.read_program("Pick_BFRACK_L.script"))
    ur_robot_ssh.close()
