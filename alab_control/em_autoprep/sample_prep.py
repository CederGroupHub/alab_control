from alab_control.ender3 import Ender3
from alab_control.em_autoprep import csv_helper
#from ender3 import Ender3
import serial
import os

CWD = os.getcwd()
path = CWD + '\\alab_control\\em_autoprep\\Positions\\'
clean_disks_filename = 'disks_tray_clean.csv'
used_disks_filename = 'disks_tray_used.csv'
equipment_filename = 'equipment.csv'
intermediate_positions_filename = 'intermediate_positions.csv'
phenom_holder_positions_filename = 'phenom_stubs.csv'
phenom_handler_filename = 'phenom_handler.csv'
stubs_tray_filename = 'stubs_tray.csv'

def procedureEnd():
    r.moveto(*r.intermediate_pos["ZHOME"])
    r.moveto(*r.intermediate_pos["HOME"])

class SamplePrepEnder3(Ender3):
    """This class is for controlling the Ender3 3D printer for sample preparation."""

    #MAX_CRUCIBLE_HEIGHT = 60  # maximum height (in mm) of the crucible
    CRUCIBLE_HEIGHT = 39

    # positions
    clean_disk_pos = csv_helper.read_CSV_into_positions(
        path=path + clean_disks_filename
    )
    used_disk_pos = csv_helper.read_CSV_into_positions(
        path=path + used_disks_filename
    )
    equipment_pos = csv_helper.read_CSV_into_positions(
        path=path + equipment_filename
    )
    intermediate_pos = csv_helper.read_CSV_into_positions(
        path=path + intermediate_positions_filename
    )
    used_stub_pos = csv_helper.read_CSV_into_positions(
        path=path + phenom_holder_positions_filename
    )
    phenom_handler_pos = csv_helper.read_CSV_into_positions(
        path=path + phenom_handler_filename
    )
    clean_stub_pos = csv_helper.read_CSV_into_positions(
        path=path + stubs_tray_filename
    )


if __name__ == "__main__":
    print(
        "**************************************************************************** \n "
    )
    print("Hello! This code will guide you on using the Automated Sample Prep \n")
    print(
        "**************************************************************************** \n "
    )

    try:
        r = SamplePrepEnder3("COM6") 
    except Exception as var_error:
        print(f"An error occurred: {var_error}")
        print(f"These are the available connections: \n")
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            print(p)
        input("\n Edit the source code to match the MAPLE COM port. Press enter to end the program.")
        exit()

    print("Printer is resetting the positioning system. Please wait... \n")
    r.gohome()


    print("Homing head unit. Please wait...")
    r.moveto(*r.intermediate_pos["HOME"])
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
            stub_choice = input("Please enter the number of the stub you want to pick:")
            

            try:
                int(stub_choice)
                r.moveto(*r.clean_stub_pos["TSTUB" + stub_choice])
                #r.moveto(z=115)
                pump_confirm = input("Please turn on vacuum pump and press enter.")
                break
            except Exception:
                print("Invalid choice. Please try again.")

        r.moveto(*r.clean_stub_pos["STRAY_Z1"])

        r.speed = 0.005
        r.moveto(*r.clean_stub_pos["STRAY_Z2"])

        r.moveto(*r.clean_stub_pos["STRAY_Z3"])

        while True:
            picked_confirm = input(
                "Stub picked? C to continue, R to try again, M for manual, A to abort." # abort not available yet
            )
            if picked_confirm.lower() == "c":  
                break
            elif picked_confirm.lower() == "r":
                r.moveto(*r.clean_stub_pos["STRAY_Z2"])
                r.moveto(*r.clean_stub_pos["STRAY_Z3"])
                picked_confirm = input(
                    "Stub picked? If not, R to try again, C to continue."
                )
                if picked_confirm.lower() == "c":
                    break
            elif picked_confirm.lower() == "m":
                r.speed = 0.5
                r.moveto(*r.intermediate_pos["MANUAL_MODE_HOME"])
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
                input("Please type the exposure distance you need (from -25 to 30): ")
            )
            if exp_dist < -25 or exp_dist > 30:
                exp_dist = 0
                print("Invalid choice. Please try again.")
            else:
                break

        r.moveto(z=132 -  r.CRUCIBLE_HEIGHT + exp_dist)
        print("\n***** STUB READY TO BE EXPOSED *****")
        exp_confirm = input("Please press enter when the exposing is finished.")
        r.moveto(z=60)

        r.moveto(*r.used_stub_pos["PH_STUB" + stub_choice])

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
            procedureEnd()
            print("Done. Now you can shutdown the system.")
            break
        else:
            print("Invalid choice. Please try again.")

