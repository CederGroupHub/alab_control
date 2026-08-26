import logging

logger = logging.getLogger(__name__)
import time

from alab_control.door_controller import DoorController

start = time.time()
DC=DoorController(ip_address="192.168.0.42",names=["C","D"])
DC.open("C")
end = time.time()
logger.info(str('Opening C takes: ') + ' ' + str(end - start))
start = time.time()
DC=DoorController(ip_address="192.168.0.42",names=["C","D"])
DC.open("D")
end = time.time()
logger.info(str('Opening D takes: ') + ' ' + str(end - start))
logger.info('Please insert the calibrated time into the arduino code and upload')

