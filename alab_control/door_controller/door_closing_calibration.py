import logging

logger = logging.getLogger(__name__)
import time

from alab_control.door_controller import DoorController
import time

def measure_keypress_duration():
    start = time.time()
    input("Press enter to measure duration: ")
    end = time.time()
    duration = end - start
    return duration

logger.info('Press enter to start measuring keypress duration.')
input()
while True:
    duration = measure_keypress_duration()
    logger.info(str('Duration: ') + ' ' + str(duration) + ' ' + str('seconds'))
