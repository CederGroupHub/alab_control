from alab_control.ender3 import Ender3
import serial
import socket
import time
import sys

# USE THE VARIABLES BELOW TO SETUP YOUR EXPERIMENT #
EXPOSURE_DISTANCE = 10 #value between -25 and +25, measured in mm, from the top of the crucible
EXPOSURE_VOLTAGE = "10000" #value between 01000 and 30000, measured in volts
EXPOSURE_TIME = "10000" #value between 250 and 99999, measured in millli seconds


#constants for safe operation
MAX_EXPOSURE_DISTANCE = 10.0

#ADD CODE TO EVALUATE DISTANCE BEFORE THE SYSTEM STARTS WITH THE MACHINE

#speed values
SPEED_VLOW = 0.005
SPEED_LOW = 0.02
SPEED_NORMAL = 0.5

#sleep times
PAUSE = 4
PAUSE_VAC = 16

def send_command(message, host = '192.168.0.46', port = '8888'):
    port=int(port)
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host,port))
        s.sendall(message.encode())
        data = s.recv(1024)
        decoded = data.decode('utf-8')
        print('Socket reply>>'+decoded)

class SamplePrepEnder3(Ender3):
    """This class is for controlling the Ender3 3D printer for sample preparation."""


    # positions
    HOME = (90, 120, 5)
    STUB = (139.5, 133, None)
    PREP_EXP = (8, 42, None)
    Z_PREP_EXP = (None, None, 55)
    STANDBY = (15, 15, 15)
    Z_STANDBY = (None, None, 15)
    Z_STUB_PICK0 = (None, None, 101.3)
    Z_STUB_PICK1 = (None, None, 100)
    Z_STUB_PICK2 = (None, None, 97)






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
    r.moveto(*r.HOME)
    r.speed = SPEED_NORMAL
    print("Done.")
    r.moveto(*r.STUB)
    
    #time.sleep(PAUSE)
    r.moveto(*r.Z_STUB_PICK2)
    r.speed = SPEED_LOW
    r.moveto(*r.Z_STUB_PICK1)
    r.speed = SPEED_VLOW
    r.moveto(*r.Z_STUB_PICK0)
    send_command("TEMPREPVAC1")
    time.sleep(PAUSE)
    r.moveto(*r.Z_STUB_PICK1)

    r.speed = SPEED_NORMAL
    r.moveto(*r.Z_STANDBY)

    while True:
        picked_confirm = input(
            "Stub picked? C to continue, R to try again, M for manual, A to abort: "
        )
        if picked_confirm.lower() == "a":
            send_command("STANDBY")
            print("Aborted.")
            sys.exit()
        elif picked_confirm.lower() == "c":
            break
        elif picked_confirm.lower() == "r":
            send_command("STANDBY")
            r.speed = SPEED_LOW
            r.moveto(*r.Z_STUB_PICK1)
            r.moveto(*r.Z_STUB_PICK0)
            send_command("TEMPREPVAC1")
            time.sleep(PAUSE)
            picked_confirm = input(
                "Stub picked? If not, R to try again, C to continue: "
            )
            if picked_confirm.lower() == "c":
                break
        elif picked_confirm.lower() == "m":
            r.speed = SPEED_NORMAL
            r.moveto(*r.Z_STANDBY)
            r.moveto(*r.HOME)
            picked_confirm = input(
                "Press enter when the stub is properly attached."
            )
            break
        else:
            print("Invalid choice. Please try again.")

    r.speed = SPEED_NORMAL
    r.moveto(*r.Z_STANDBY)

    r.moveto(*r.HOME)
    r.moveto(*r.PREP_EXP)
    r.moveto(*r.Z_PREP_EXP)
    r.speed = SPEED_LOW
    r.moverel(z=EXPOSURE_DISTANCE)
    print("\n***** STUB WILL BE EXPOSED FOR " + EXPOSURE_TIME + " MILLI SECONDS *****")
    time.sleep(PAUSE)
    send_command("EXPOSURV"+EXPOSURE_VOLTAGE+"T"+EXPOSURE_TIME)
    print("\n***** EXPOSING *****")
    time.sleep(int(EXPOSURE_TIME)/1000+2)
    print("\n***** EXPOSING PROCEDURE FINISHED *****")
    r.speed = SPEED_NORMAL
    r.moveto(*r.Z_STANDBY)
    r.moveto(*r.HOME)
    r.moveto(*r.STUB)

    r.moveto(*r.Z_STUB_PICK1)
    r.speed = SPEED_VLOW
    r.moveto(*r.Z_STUB_PICK0)
    send_command("STANDBY")
    time.sleep(PAUSE_VAC)
    r.speed = SPEED_NORMAL
    r.moveto(*r.Z_STANDBY)
    r.moveto(*r.STANDBY)
