from alab_control.ender3 import Ender3
from alab_control.SEM_autoprep import csv_helper
#from ender3 import Ender3
import serial
import os

CWD = os.getcwd()

class SamplePrepEnder3(Ender3):
    """This class is for controlling the Ender3 3D printer for sample preparation."""



if __name__ == "__main__":

    print('\033c') #cleaning the screen to start beautifully 8-) heehee
    print(
        "**************************************************************************** \n "
    )
    print("Hello! This code will help you with communicating with the 3D Printer \n")
    print(
        "**************************************************************************** \n "
    )

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
    r.moveto(10,10,10)
    r.speed = 0.2
    print("Done.")


    while True:


        while True:
            # Ask the user to choose part 1 or part 2
            getpos = input("Enter the coordinates separated with spaces: ")
            getpos_list = getpos.split()
            getpos_list = [float(num) for num in getpos_list]
            TESTER = tuple(getpos_list)
            
            try:
                r.moveto(x=TESTER[0],y=TESTER[1],z=TESTER[2])
                print("REMINDER: Always be aware of obstacles! Move Z up first to avoid breaking things!!! \n")
                break
            except Exception:
                print("Invalid choice. Please try again.")
            


