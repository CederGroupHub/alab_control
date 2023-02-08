import time

from alab_control.door_controller import DoorController

start = time.time()
DC=DoorController(ip_address="192.168.0.42",names=["C","D"])
DC.open("C")
end = time.time()
print("Opening C takes: ",end - start)
start = time.time()
DC=DoorController(ip_address="192.168.0.42",names=["C","D"])
DC.open("D")
end = time.time()
print("Opening D takes: ",end - start)
print("Please insert the calibrated time into the arduino code and upload")

