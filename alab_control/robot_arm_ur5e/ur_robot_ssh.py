import re
from pathlib import Path
from typing import Optional

import paramiko


def get_header(file_string: str):
    return re.search(
        r"# begin: URCap Installation Node.*# end: URCap Installation Node",
        file_string,
        re.DOTALL
    ).group(0)


def replace_header(orginal_file: str, new_header: str):
    return re.sub(
        r"# begin: URCap Installation Node.*# end: URCap Installation Node",
        new_header,
        orginal_file,
        flags=re.DOTALL
    )


class URRobotSSH:
    def __init__(self, ip: str):
        self.ip = ip
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(self.ip, username="root", password="easybot")

    def read_program(self, file_name: str, base: str = "/programs", header_file_name: Optional[str] = None) -> str:
        with self._ssh.open_sftp() as sftp:
            with sftp.open((Path(base) / file_name).as_posix(), "r") as f:
                program_file = f.read().decode("utf-8")
            if header_file_name is not None:
                with sftp.open((Path(base) / header_file_name).as_posix(), "r") as f:
                    header_file = f.read().decode("utf-8")
                program_file = replace_header(program_file, get_header(header_file))
        return program_file

    def close(self):
        self._ssh.close()


if __name__ == '__main__':
    ur_robot_ssh = URRobotSSH("192.168.0.23")
    print(ur_robot_ssh.read_program("shaking.script", header_file_name="empty.script"))
    ur_robot_ssh.close()
