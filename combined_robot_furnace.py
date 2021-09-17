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

import time
from datetime import timedelta
from alab_control.furnace_epc_3016.furnace_driver import FurnaceController, SegmentType
from alab_control.robot_arm_ur5e import URRobot
import threading
import msvcrt

#Input
robot_ip="192.168.132.154"
furnace_ip="192.168.132.154"
set_point=50 #Set point temperature in Celcius
ramp_time=6 #Ramp time in minutes
dwell_time=1 #Dwell time in minutes

#Object Classes and Methods
class myThread (threading.Thread):
    def __init__(self, name, delay, task):
        threading.Thread.__init__(self)
        self.name = name
        self.delay = delay
        self.task = task
        self.taskComplete = False
    def run(self):
        print ("Starting " + self.name)
        while not self.taskComplete:
            self.task()
            time.sleep(self.delay)
        print ("Exiting " + self.name)

class myFurnace (FurnaceController):
    def __init__(self):
        self.status="idle" #idle, running
        self.tmp=False
    def check_status(self):
        if self.tmp!=self.is_running():
            self.tmp=self.is_running()
            self.status_handler()
    #Object status change might induce event
    def status_handler(self):
        if (self.status=="idle" and self.is_running()):
            self.status="running"
        if (self.status=="running" and not self.is_running()):
            self.status="idle"
    def simple_heating(self,set_point,ramp_time,dwell_time):
        self.furnace._configure_segment_i(i=1, segment_type=SegmentType.RAMP_TIME, target_setpoint=set_point,
                                            time_to_target=timedelta(minutes=ramp_time))
        self.furnace._configure_segment_i(i=2, segment_type=SegmentType.DWELL, duration=timedelta(minutes=dwell_time))
        self.furnace._configure_segment_i(i=3, segment_type=SegmentType.STEP, target_setpoint=0)
        self.furnace._configure_segment_i(i=4, segment_type=SegmentType.END)

class myURRobot (URRobot):
    def __init__(self):
        self.status="idle" #idle, in, out
        self.mode="STOPPED" #STOPPED, PLAYING, PAUSED
    def check_status(self):
        self.mode=self.get_current_mode()

class myButtons ():
    def __init__(self):
        self.play=False
        self.pause=False
        self.stop=False
        self.key=b''
    def check_status(self):
        if msvcrt.kbhit():
            self.key = msvcrt.getch()
            if self.key==b'j':
                self.play=True
            if self.key==b'k':
                self.pause=True
            if self.key==b'l':
                self.stop=True

#System Event Handlers, an event due to object(s)'s status changes will require actuations 
#which in turn will change object(s)'s status
def status_checking_and_event_handler(test_furnace,test_robot,test_buttons):
    #when play button is pressed, 
    ## if robot is idle in task, give robot first task and play it
    ## if robot is not idle in task, continue it
    #when pause button is pressed, pause robot and hold furnace
    #when stop button is pressed, reset furnace and stop robot, human technical assistance is required
    test_buttons.check_status()
    if (test_buttons.play or test_buttons.pause or test_buttons.stop):
        #check whether play and pause buttons are pressed together. 
        #If so, stop will be initiated because error has been detected
        if (test_buttons.play and test_buttons.pause):
            test_buttons.stop=True
        if (test_buttons.stop):
            test_robot.stop()
            test_furnace.reset_program()
            test_buttons.stop=False
        if (test_buttons.pause):
            test_robot.pause()
            test_furnace.test_furnace.hold_program()
            test_buttons.pause=False
        if (test_buttons.play):
            test_buttons.play=False
            if (test_robot.status=="idle" and test_furnace.status=="idle" and test_robot.mode=="STOPPED"):
                #Play button pressed (Crucible ready)
                test_robot.status="in"
                test_robot.load("load_in_crucible.urp") #!!!
                test_robot.play()
            if (test_robot.status!="idle" and test_furnace.status!="idle" and test_robot.mode=="PAUSED"):
                #Continue any ongoing task
                test_furnace.run_program()
                test_robot.continue_play()
    furnace_status_temp=test_furnace.status #take current status
    test_furnace.check_status() #check new status
    if(furnace_status_temp!=test_furnace.status):
        if(test_furnace.status=="idle" and furnace_status_temp=="running"):
            #Furnace has done heating and cooling down
            test_robot.status="out"
            test_robot.load("take_out_crucible.urp") #!!!
            test_robot.play()
    robot_status_temp=test_robot.status
    test_robot.check_status()
    if(test_robot.status!=robot_status_temp):
        if(test_robot.status=="idle" and robot_status_temp=="in"):
            #Robot has loaded in the crucible
            test_furnace.simple_heating(set_point,ramp_time,dwell_time)
            test_furnace.run_program()
        if(test_robot.status=="idle" and robot_status_temp=="out"):
            #Robot has taken out the crucible
            print("Program has been successfully carried out")
#Main Program
##Initialization
test_furnace=myFurnace(address=furnace_ip)
test_robot=myURRobot(ip=robot_ip)
test_buttons=myButtons()

while True:
    status_checking_and_event_handler(test_furnace,test_robot,test_buttons)
    time.sleep(0.1)