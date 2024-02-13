import cv2
import time
import os
import paramiko
import scp
from datetime import datetime

# Camera variables
RESOLUTION = [1280, 720]
period = 1
num_pics = 1
ADJUST = 0
TIME_ADJUST = 0.047
#time.sleep(5)
cam = cv2.VideoCapture(0)
cam.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUTION[0])
cam.set(cv2.CAP_PROP_FRAME_HEIGHT,RESOLUTION[1])
LOCAL_FOLDER_PATH = '/Users/CederALab/Desktop/Outputs/'

# File Transter variables
REMOTE_FOLDER_PATH = '/Users/yuhan/Desktop/Outputs/'
USERNAME = 'User'
IP = '128.3.19.55'
PORT = 22  # Default SSH port
PASSWORD = 'PassWord'

def transfer_file_to_pc(local_path, remote_path, mac_username, mac_ip, mac_port, mac_password):
    # Establish an SSH connection to the Mac
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(mac_ip, port=mac_port, username=mac_username, password=mac_password)

    # Use SCP to copy the file from Raspberry Pi to Mac
    with scp.SCPClient(ssh.get_transport()) as s:
        s.put(local_path, remote_path)

    # Close the SSH connection
    ssh.close()

num_pics = int(input("Please enter the number of pictures you want"))
period = int(input("Please enter the period in seconds"))

for i in range(ADJUST * -1, num_pics):
    ret, image = cam.read()
    if i >= 0:
        cv2.imwrite(LOCAL_FOLDER_PATH + str(i) + '.jpg', image)
        
    time.sleep(period - TIME_ADJUST)
    print(str(datetime.now()))
cam.release()
cv2.destroyAllWindows()

for i in range(0, num_pics):
    transfer_file_to_pc(LOCAL_FOLDER_PATH + str(i) + '.jpg', REMOTE_FOLDER_PATH + str(i) + '.jpg', USERNAME, IP, PORT, PASSWORD)
