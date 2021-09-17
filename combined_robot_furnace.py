"""
This program will demonstrate how a workflow between robot and furnace can be done.
1. Robot opens the furnace
2. Robot takes crucible and put it into the furnace
3. Robot closes the furnace
4. Ramp temperature to 50 C
5. Dwell on 50 C for 1 minute
6. Once the dwelling is done, the furnace turns off, and automatically send a signal when it is already cold (periodic checking is set)
7. Robot automatically opens the furnace, take the crucible out, and close the furnace
"""

import msvcrt
import threading
import time
from datetime import timedelta

from alab_control.furnace_epc_3016.furnace_driver import FurnaceController, SegmentType
from alab_control.robot_arm_ur5e import URRobot

# Input
ROBOT_IP = "192.168.182.132"
FURNACE_IP = "192.168.111.222"
SET_POINT = 30  # Set point temperature in Celsius
RAMP_TIME = 6  # Ramp time in minutes
DWELL_TIME = 1  # Dwell time in minutes


# Object Classes and Methods
class MyThread(threading.Thread):
    def __init__(self, name, delay, task):
        threading.Thread.__init__(self)
        self.name = name
        self.delay = delay
        self.task = task
        self.task_complete = False

    def run(self):
        print("Starting " + self.name)
        while not self.task_complete:
            self.task()
            time.sleep(self.delay)
        print("Exiting " + self.name)


class MyFurnace(FurnaceController):
    def __init__(self, *args, **kwargs):
        super(MyFurnace, self).__init__(*args, **kwargs)
        self.status = "idle"  # idle, running
        self.tmp = False

    def check_status(self):
        if self.tmp != self.is_running():
            self.tmp = self.is_running()
            self.status_handler()

    # Object status change might induce event
    def status_handler(self):
        if self.status == "idle" and self.is_running():
            self.status = "running"
        if self.status == "running" and not self.is_running():
            self.status = "idle"

    def simple_heating(self, set_point, ramp_time, dwell_time):
        self._configure_segment_i(i=1, segment_type=SegmentType.RAMP_TIME, target_setpoint=set_point,
                                  time_to_target=timedelta(minutes=ramp_time))
        self._configure_segment_i(i=2, segment_type=SegmentType.DWELL, duration=timedelta(minutes=dwell_time))
        self._configure_segment_i(i=3, segment_type=SegmentType.STEP, target_setpoint=0)
        self._configure_segment_i(i=4, segment_type=SegmentType.END)


class MyURRobot(URRobot):
    def __init__(self, *args, **kwargs):
        super(MyURRobot, self).__init__(*args, **kwargs)
        self.status = "idle"  # idle, in, out
        self.mode = "STOPPED"  # STOPPED, PLAYING, PAUSED

    def check_status(self):
        self.mode = self.get_current_mode().name


class MyButtons:
    def __init__(self):
        self.play = False
        self.pause = False
        self.stop = False
        self.key = b''

    def check_status(self):
        if msvcrt.kbhit():
            self.key = msvcrt.getch()
            if self.key == b'j':
                self.play = True
            if self.key == b'k':
                self.pause = True
            if self.key == b'l':
                self.stop = True


# System Event Handlers, an event due to object(s)'s status changes will require actuation
# which in turn will change object(s)'s status
def status_checking_and_event_handler(furnace, robot, buttons):
    # when play button is pressed,
    #    # if robot is idle in task, give robot first task and play it
    #    # if robot is not idle in task, continue it
    # when pause button is pressed, pause robot and hold furnace
    # when stop button is pressed, reset furnace and stop robot, human technical assistance is required
    buttons.check_status()
    if buttons.play or buttons.pause or buttons.stop:
        # check whether play and pause buttons are pressed together.
        # if so, stop will be initiated because error has been detected
        if buttons.play and buttons.pause:
            buttons.play = False
            buttons.pause = False
            buttons.stop = True
        if buttons.stop:
            buttons.play = False
            buttons.pause = False
            buttons.stop = False
            robot.stop()
            furnace.reset_program()
        if buttons.pause:
            buttons.pause = False
            robot.pause()
            furnace.furnace.hold_program()
        if buttons.play:
            buttons.play = False
            if robot.status == "idle" and furnace.status == "idle" and robot.mode == "STOPPED":
                # Play button pressed (Crucible ready) [Event 0]
                robot.status = "in"
                robot.load("load_in_crucible.urp")  # !!!
                robot.play()
            if robot.mode == "PAUSED":
                # Continue any ongoing task [Event 6]
                furnace.run_program()
                robot.continue_play()
            # Other than these two cases, the play button wont work
    furnace_status_temp = furnace.status  # take current status
    furnace.check_status()  # check new status
    if furnace_status_temp != furnace.status:
        if furnace.status == "idle" and furnace_status_temp == "running":
            # Furnace has done heating and cooling down [Event 2-4]
            robot.status = "out"
            robot.load("take_out_crucible.urp")  # !!!
            robot.play()
    robot_status_temp = robot.status
    robot.check_status()
    if robot.status != robot_status_temp:
        if robot.status == "idle" and robot_status_temp == "in":
            # Robot has loaded in the crucible, furnace starts heating up [Event 1]
            furnace.simple_heating(SET_POINT, RAMP_TIME, DWELL_TIME)
            furnace.run_program()
        if robot.status == "idle" and robot_status_temp == "out":
            # Robot has taken out the crucible [Event 5]
            print("Program has been successfully carried out")


# Main Program
# Initialization
furnace = MyFurnace(address=FURNACE_IP)
robot = MyURRobot(ip=ROBOT_IP)
buttons = MyButtons()


# Periodic Loop 100ms
while True:
    status_checking_and_event_handler(furnace, robot, buttons)
    time.sleep(0.1)
