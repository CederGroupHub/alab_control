from alab_control.ender3 import Ender3
import serial
import socket
import time
import sys

# USE THE VARIABLES BELOW TO SETUP YOUR EXPERIMENT #
EXPOSURE_DISTANCE = 21 #value between -25 and +25, measured in mm, from the top of the crucible
EXPOSURE_VOLTAGE = "10000" #value between 01000 and 30000, measured in volts
EXPOSURE_TIME = "05000" #value between 250 and 99999, measured in millli seconds
DESTINATION = 0 #0 is to return to stub holder. 1 is to place on phenom stage
MANUAL_STUB_LOAD = 0 #0 is to automatically pick the stubs from the stub holder. 1 is to manually place them on the needle
TAKE_STUB_PIC = 0 #0 is to skip taking a picture of the exposed stub. 1 takes the pic


#constants for safe operation
crucible_exp_dist = 71 #71 is the standard
MAX_EXPOSURE_DISTANCE = 25.0
CRUCIBLE_HEIGHT = 39

#speed values
SPEED_VLOW = 0.005
SPEED_LOW = 0.02
SPEED_NORMAL = 0.5

#sleep times
PAUSE = 2
PAUSE_VAC = 11

def send_command(message, host = '192.168.0.46', port = '8888'):
    port=int(port)
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host,port))
        s.sendall(message.encode())
        data = s.recv(1024)
        decoded = data.decode('utf-8')
        #print('Socket reply>>'+decoded)
        return decoded

class SamplePrepEnder3(Ender3):
    """This class is for controlling the Ender3 3D printer for sample preparation."""


    # positions
    CENTRE_POS = (90, 120, 5)
    PREP_EXP = (60, 48, None)
    STANDBY = (15, 15, 15)
    Z_STANDBY = (None, None, 5)
    STUB = (51.3, 126.8, None)
    Z_STUB_PICK2 = (None, None, 61)
    Z_STUB_PICK1 = (None, None, 67)
    Z_STUB_PICK0 = (None, None, 70)
    LASER = (165, 145, None)
    Z_LASER = (None, None, 62)
    MIRROR = (103, 97, None)
    Z_MIRROR = (None, None, 65)
    ROTATOR_0 = (120, 111.5, None)
    Z_ROTATOR_0 = (None, None, 66.5)
    ROTATOR_1 = (134, 111.5, 66.5) #Z value MUST agree with Z_ROTATOR_0
    GRIPPER_0 = (110, 131, None)
    Z_GRIPPER_0 = (None, None, 51)
    GRIPPER_1 = (95, None, None)
    PHENOM_POS8 = (133, 76, None)
    Z_PHENOM_POS8_1 = (None, None, 32)
    Z_PHENOM_POS8_0 = (None, None, 35)

    #we need 18 clean stubs
    #we need 18 prepared stubs
    #we need 40 grid positions




if __name__ == "__main__":
    print('\033c') #cleaning the terminal screen
    print(
        "**************************************************************************** \n "
    )
    print("Hello! This code will guide you on using the Automated Sample Prep \n")
    print(
        "**************************************************************************** \n "
    )

    print("Starting the control panel...")
    try:
        send_command("STANDBY")
    except Exception as var_error:
        print(f"The execution was halted, an error occurred: {var_error}")
        sys.exit()
    else:
        time.sleep(PAUSE)
        print("Done.")

    time.sleep(2)    

    try:
        r = SamplePrepEnder3("COM7") 
    except Exception as var_error:
        print(f"An error occurred: {var_error}")
        print(f"These are the available connections: \n")
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            print(p)
        input("\n Press enter to end the program.")
        exit()

    print("Printer is resetting the positioning system. Please wait... \n")
    r.gohome()

    print("Homing head unit. Please wait...")
    r.moveto(*r.STANDBY)
    r.speed = SPEED_NORMAL
    print("Done.")
    r.moveto(*r.STUB)
    print("Turning on vacuum pump 2 (TEMPORARY SOLUTION: PUMP 1 IS STANDARD - SEMPREPVAC1)...")
    reply = send_command("TEMPREPVAC1")
    print("Control panel replied >>" + reply)
    time.sleep(PAUSE)
    r.moveto(*r.Z_STUB_PICK2)
    r.speed = SPEED_LOW
    r.moveto(*r.Z_STUB_PICK1)
    r.speed = SPEED_VLOW
    r.moveto(*r.Z_STUB_PICK0)
    r.moveto(*r.Z_STUB_PICK1)

    r.speed = SPEED_NORMAL
    r.moveto(*r.Z_STANDBY)


    stub_pick_trials = 0
    while True:
        if stub_pick_trials >= 2:
            print("Stub not picked 3 times in a row. Aborted.")
            sys.exit()

        print("Checking if stub was picked...")
        r.moveto(*r.Z_STANDBY)
        r.moveto(*r.LASER)
        r.moveto(*r.Z_LASER)
        decoded = send_command("SEMPREPTEST")
        if decoded == "LASER1":
            print("Stub was picked!")
            break
        else:
            print("...Trying again...")
            r.moveto(*r.Z_STANDBY)
            r.moveto(*r.STUB)
            r.moveto(*r.Z_STUB_PICK2)
            r.speed = SPEED_LOW
            r.moveto(*r.Z_STUB_PICK1)
            r.speed = SPEED_VLOW
            r.moveto(*r.Z_STUB_PICK0)
            r.moveto(*r.Z_STUB_PICK1)
            r.speed = SPEED_NORMAL
            r.moveto(*r.Z_STANDBY)
            stub_pick_trials = stub_pick_trials+1


    r.speed = SPEED_NORMAL
    r.moveto(*r.Z_STANDBY)

    r.moveto(*r.CENTRE_POS)

    
    r.moveto(*r.PREP_EXP)
    r.moveto(z=crucible_exp_dist - CRUCIBLE_HEIGHT)

    r.moveto(z=crucible_exp_dist -  CRUCIBLE_HEIGHT + EXPOSURE_DISTANCE)
    print("\n***** STUB WILL BE EXPOSED FOR " + EXPOSURE_TIME + " MILLI SECONDS *****")
    time.sleep(PAUSE)
    send_command("EXPOSURV"+EXPOSURE_VOLTAGE+"T"+EXPOSURE_TIME)
    print("\n***** EXPOSING *****")
    time.sleep(int(EXPOSURE_TIME)/1000+2)
    print("\n***** EXPOSING PROCEDURE FINISHED *****")
    r.moveto(*r.Z_STANDBY)
    #r.moveto(*r.STANDBY)

    if TAKE_STUB_PIC == 1:
        print("\nTaking a picture of the stub...")
        r.moveto(*r.MIRROR)
        r.moveto(*r.Z_MIRROR)
        print("\n... **CLICK** ...")
        time.sleep(2)
        print("\nDone.")
        r.moveto(*r.Z_STANDBY)
    

    if DESTINATION == 0:
        print("\nStoring stub back on the stub holder...")
        r.moveto(*r.STUB)
        r.moveto(*r.Z_STUB_PICK1)
        r.speed = SPEED_VLOW
        r.moveto(*r.Z_STUB_PICK0)
        send_command("STANDBY")
        time.sleep(PAUSE_VAC)
        r.speed = SPEED_NORMAL
        print("\nDone.")
        r.moveto(*r.Z_STANDBY)
        r.moveto(*r.STANDBY)
    elif DESTINATION == 1:
        print("\nStoring stub on the phenom stage...")
        r.moveto(*r.ROTATOR_0)
        r.moveto(*r.Z_ROTATOR_0)
        r.speed = SPEED_VLOW
        r.moveto(*r.ROTATOR_1)
        send_command("STANDBY")
        time.sleep(PAUSE_VAC/2)
        r.speed = SPEED_NORMAL
        r.moveto(*r.Z_STANDBY)
        send_command("SEMPREPR155")
        r.moveto(*r.GRIPPER_0)
        r.moveto(*r.Z_GRIPPER_0)
        send_command("SEMSTORG105")
        time.sleep(2)
        r.speed = SPEED_VLOW
        r.moveto(*r.GRIPPER_1)
        r.speed = SPEED_NORMAL
        r.moveto(*r.Z_STANDBY)
        send_command("SEMPREPR020")
        send_command("PHLIDMVL040")
        time.sleep(7)
        r.moveto(*r.PHENOM_POS8)
        r.moveto(*r.Z_PHENOM_POS8_1)
        r.speed = SPEED_VLOW
        r.moveto(*r.Z_PHENOM_POS8_0)
        send_command("SEMSTORG085")
        r.speed = SPEED_NORMAL
        r.moveto(*r.Z_STANDBY)
        send_command("SEMSTORG000")
        send_command("PHLIDMVL150")
        r.moveto(*r.STANDBY)

        




        print("\nDone.")
        #r.moveto(*r.Z_STANDBY)
        #r.moveto(*r.STANDBY)