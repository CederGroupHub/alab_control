from alab_control.ender3 import Ender3
#from ender3 import Ender3
import serial

EXPOSURE_DISTANCE = 25.0


class SamplePrepEnder3(Ender3):
    """This class is for controlling the Ender3 3D printer for sample preparation."""

    #MAX_CRUCIBLE_HEIGHT = 60  # maximum height (in mm) of the crucible
    CRUCIBLE_HEIGHT = 39
    

    # positions
    HOME = (90, 120, 60)
    STUB1 = (4.5, 129.6, None)  # z is set later
    STUB2 = (20.5, 129.5, None)  # z is set later
    PREP_EXP = (110, 18.5, None)

    #we need 18 clean stubs
    #we need 18 prepared stubs
    #we need 40 grid positions




if __name__ == "__main__":
    print('\033c') #cleaning the screen to start beautifully 8-) heehee
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
        input("\n Press enter to end the program.")
        exit()

    print("Printer is resetting the positioning system. Please wait... \n")
    r.gohome()

    print("Homing head unit. Please wait...")
    r.moveto(*r.HOME)
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
            if stub_choice == "1":
                r.moveto(*r.STUB1)
                break
            elif stub_choice == "2":
                r.moveto(*r.STUB2)
                break
            else:
                print("Invalid choice. Please try again.")

        pump_confirm = input("Please turn on vacuum pump and press enter.")
        r.moveto(z=99)
        r.speed = 0.02
        r.moveto(z=104)
        r.speed = 0.005
        r.moveto(z=107.3)

        r.moveto(z=104)

        while True:
            picked_confirm = input(
                "Stub picked? C to continue, R to try again, M for manual, A to abort: "
            )
            if picked_confirm.lower() == "c":  # abort not available yet
                break
            elif picked_confirm.lower() == "r":
                r.moveto(z=107.3)
                r.moveto(z=104)
                picked_confirm = input(
                    "Stub picked? If not, R to try again, C to continue: "
                )
                if picked_confirm.lower() == "c":
                    break
            elif picked_confirm.lower() == "m":
                r.speed = 0.5
                r.moveto(z=60)
                r.moveto(*r.HOME)
                picked_confirm = input(
                    "Press enter when the stub is properly attached."
                )
                break
            else:
                print("Invalid choice. Please try again.")

        r.speed = 0.5
        r.moveto(z=60)

        r.moveto(*r.HOME)
        #input("PRESS ENTER TO GO TO EXPOSURE POSITION")


        r.moveto(*r.PREP_EXP)
        r.moveto(z=132 - r.CRUCIBLE_HEIGHT)

        while True:
            exp_dist = float(
                input("Please type the exposure distance you need (from -25 to 25): ")
            )
            if exp_dist < EXPOSURE_DISTANCE * -1 or exp_dist > EXPOSURE_DISTANCE:
                exp_dist = 0
                print("Invalid choice. Please try again.")
                #Alex, can you make the exposition distance in decimals instead of integers? 
            else:
                break

        r.moveto(z=132 -  r.CRUCIBLE_HEIGHT + exp_dist)
        print("\n***** STUB READY TO BE EXPOSED *****")
        exp_confirm = input("Please press enter when the exposing is finished.")
        r.moveto(z=60)
        r.moveto(*r.HOME)

        if stub_choice == "1":
            r.moveto(*r.STUB1)
        elif stub_choice == "2":
            r.moveto(*r.STUB2)
        else:
            print("Invalid choice. Please try again.")

        r.moveto(z=105)
        r.speed = 0.005
        r.moveto(z=107.3)
        pump_confirm = input("Please turn off vacuum pump and press enter.")
        r.speed = 0.5
        r.moveto(z=60)
        r.moveto(*r.HOME)

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
