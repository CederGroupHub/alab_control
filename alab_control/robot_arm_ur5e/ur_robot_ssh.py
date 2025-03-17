import gzip
from pathlib import Path
from typing import Optional

import paramiko

from alab_control.robot_arm_ur5e.utils import get_header, replace_header


class URRobotSSH:
    def __init__(self, ip: str):
        self.ip = ip
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(self.ip, username="root", password="easybot")

    def read_file(self, file_path: str):
        with self._ssh.open_sftp() as sftp:
            with sftp.open(Path(file_path).as_posix(), "r") as f:
                file = f.read().decode("utf-8")
        return file

    def read_program(self, file_name: str, base: str = "/programs", header_file_name: Optional[str] = None) -> str:
        with self._ssh.open_sftp() as sftp:
            with sftp.open((Path(base) / file_name).as_posix(), "r") as f:
                program_file = f.read().decode("utf-8")
            if header_file_name is not None:
                with sftp.open((Path(base) / header_file_name).as_posix(), "r") as f:
                    header_file = f.read().decode("utf-8")
                program_file = replace_header(program_file, get_header(header_file))
        return program_file

    def write_program(self, file_name: str, program_string: str, base: str = "/programs"):
        with self._ssh.open_sftp() as sftp:
            with sftp.open((Path(base) / file_name).as_posix(), "w") as f:
                f.write(program_string)

    def read_urp_program(self, file_name: str, base: str = "/programs"):
        with self._ssh.open_sftp() as sftp:
            with sftp.open((Path(base) / file_name).as_posix(), "r") as f:
                compressed_program = f.read()
                program_file = gzip.decompress(compressed_program).decode("utf-8")
        return program_file

    def write_urp_program(self, file_name: str, program_string: str, base: str = "/programs"):
        with self._ssh.open_sftp() as sftp:
            compressed_program = gzip.compress(program_string.encode("utf-8"))
            with sftp.open((Path(base) / file_name).as_posix(), "wb") as f:
                f.write(compressed_program)
    
    def upload_file(self, local_file_path: str, remote_file_path: str):
        with self._ssh.open_sftp() as sftp:
            sftp.put(local_file_path, remote_file_path)

    def mkdir(self, folder_path: str, exist_ok: bool = True):
        with self._ssh.open_sftp() as sftp:
            try:
                sftp.stat(folder_path)
                exists = True
            except FileNotFoundError:
                exists = False
            if not exists:
                sftp.mkdir(folder_path)
            else:
                if not exist_ok:
                    raise FileExistsError(f"Folder {folder_path} already exists")

    def remove_file(self, file_path: str):
        with self._ssh.open_sftp() as sftp:
            sftp.remove(file_path)
        
    def download_folder(self, remote_folder_path: str, local_folder_path: str, remove_remote_files: bool = False):
        """
        Sync a remote folder to a local folder.
        Download files from the remote folder that are not in the local folder.
        Remove files from the remote folder that are downloaded if remove_remote_files is True.
        """
        with self._ssh.open_sftp() as sftp:
            for remote_file in sftp.listdir(remote_folder_path):
                local_file = Path(local_folder_path) / remote_file
                if not local_file.exists():
                    sftp.get(remote_folder_path + "/" + remote_file, local_file.as_posix())
                    if remove_remote_files:
                        sftp.remove(remote_folder_path + "/" + remote_file)

    def close(self):
        self._ssh.close()


if __name__ == '__main__':
    ur_robot_ssh = URRobotSSH("192.168.0.23")
    print(ur_robot_ssh.read_program("shaking.script", header_file_name="empty.script"))
    ur_robot_ssh.close()
