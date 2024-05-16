import socket
import serial
import os
import sys

CWD = os.getcwd()

def send_command(message, host = '192.168.0.46', port = '8888'):
    port=int(port)
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host,port))
        s.sendall(message.encode())
        data = s.recv(1024)
        decoded = data.decode('utf-8')
        print('Socket reply>>'+decoded)


if __name__ == "__main__":

    print('\033c') #cleaning the screen to start beautifully 8-) heehee
    print(
        "**************************************************************************** \n "
    )
    print("Hello! This code will guide you on positioning the needle or leveling the bed \n")
    print(
        "**************************************************************************** \n "
    )

    print("Starting the control panel: \n")

    try:
        send_command("STANDBY")
    except Exception as var_error:
        print(f"The execution was halted, an error occurred: {var_error}")
        sys.exit()

    while True:

        # Ask the user to choose part 1 or part 2
        ucommand = input("Enter the command: ")
        
        try:
            send_command(ucommand)
        except Exception as var_error:
            print(f"The execution was halted, an error occurred: {var_error}")
            #sys.exit()

