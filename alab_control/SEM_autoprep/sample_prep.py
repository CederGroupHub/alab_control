from alab_control.ender3 import Ender3
from alab_control.SEM_autoprep.Tests import csv_helper
#from ender3 import Ender3
import serial
import os

CWD = os.getcwd()
path = CWD + '\\alab_control\\SEM_autoprep\\Tests\\SampleFile.csv'

class SamplePrepEnder3(Ender3):
    """This class is for controlling the Ender3 3D printer for sample preparation."""

    #MAX_CRUCIBLE_HEIGHT = 60  # maximum height (in mm) of the crucible
    CRUCIBLE_HEIGHT = 39

    # positions
    positions = csv_helper.read_CSV_into_positions(path)


if __name__ == "__main__":
    print(
        "**************************************************************************** \n "
    )
    print("Hello! This code will guide you on using the Automated Sample Prep \n")
    print(
        "**************************************************************************** \n "
    )
    print(
        "The following lines show your COM ports.\nPlease select your MAPPLE printer by typing its number: \n"
    )

    try:
        r = SamplePrepEnder3("COM3") 
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
    r.moveto(*r.positions["HOME"])
    r.speed = 0.5
    print("Done.")
    
    
    while True:
        '''
    
        while True:
            cruc_height = int(
                input("Please type the height of the crucible you are using (in mm): ")
            )
            if cruc_height > r.MAX_CRUCIBLE_HEIGHT:
                cruc_height = 1
                print("Invalid choice. Please try again.")
            else:
                break
        '''

        while True:
            # Ask the user to choose part 1 or part 2
            stub_choice = input("Please enter 1 for Stub 1 or 2 for Stub 2: ")
            r.moveto(x=35, y=173.8, z=60)
            r.moveto(z=115)
            pump_confirm = input("Please turn on vacuum pump and press enter.")

            try:
                int(stub_choice)
                r.moveto(*r.positions["STUB" + stub_choice])
                break
            except Exception:
                print("Invalid choice. Please try again.")

        r.moveto(z=133)

        r.speed = 0.005
        r.moveto(z=141.5)

        r.moveto(z=137)

        while True:
            picked_confirm = input(
                "Stub picked? C to continue, R to try again, M for manual, A to abort."
            )
            if picked_confirm.lower() == "c":  # abort not available yet
                break
            elif picked_confirm.lower() == "r":
                r.moveto(z=141.5)
                r.moveto(z=137)
                picked_confirm = input(
                    "Stub picked? If not, R to try again, C to continue."
                )
                if picked_confirm.lower() == "c":
                    break
            elif picked_confirm.lower() == "m":
                r.moveto(x=20, y=120, z=15)
                picked_confirm = input(
                    "Press enter when the stub is properly attached."
                )
                break
            else:
                print("Invalid choice. Please try again.")

        r.speed = 0.5
        r.moveto(z=60)
        r.moveto(x=89, y=57)
        r.moveto(x=89, y=57)
        r.moveto(z=132 - r.CRUCIBLE_HEIGHT)

        while True:
            exp_dist = float(
                input("Please type the exposure distance you need (from -25 to 25): ")
            )
            if exp_dist < -25 or exp_dist > 25:
                exp_dist = 0
                print("Invalid choice. Please try again.")
            else:
                break

        r.moveto(z=132 -  r.CRUCIBLE_HEIGHT + exp_dist)
        print("\n***** STUB READY TO BE EXPOSED *****")
        exp_confirm = input("Please press enter when the exposing is finished.")
        r.moveto(z=60)

        if stub_choice == "1":
            r.moveto(x=23.8, y=173.8)
        elif stub_choice == "2":
            r.moveto(x=23.8, y=173.8)
        else:
            print("Invalid choice. Please try again.")

        r.moveto(z=137)
        r.speed = 0.005
        r.moveto(z=141)
        pump_confirm = input("Please turn off vacuum pump and press enter.")
        r.moveto(z=137)
        r.speed = 0.5
        r.moveto(z=60)
        r.moveto(x=90, y=120, z=60)

        more_confirm = input("Do you have more samples to expose? Y/N and press enter:")
        if more_confirm == "y" or more_confirm == "Y":
            print("Restarting the procedure!")
        elif more_confirm == "n" or more_confirm == "N":
            print("Wait until is safe to shutdown. Preparing...")
            r.moveto(x=15, y=15, z=15)
            print("Done. Now you can shutdown the system.")
            break
        else:
            print("Invalid choice. Please try again.")
