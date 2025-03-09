from Phidget22.Devices.DCMotor import *
from Phidget22.Devices.Encoder import *


def onPositionChange(self, positionChange, timeChange, indexTriggered):
    print("PositionChange: " + str(positionChange))
    print("TimeChange: " + str(timeChange))
    print("IndexTriggered: " + str(indexTriggered))
    print("getPosition: " + str(self.getPosition()))
    print("----------")


def main():
    dcMotor0 = DCMotor()
    encoder0 = Encoder()

    dcMotor0.setDeviceSerialNumber(662405)
    encoder0.setDeviceSerialNumber(662405)

    encoder0.setOnPositionChangeHandler(onPositionChange)

    dcMotor0.openWaitForAttachment(5000)
    encoder0.openWaitForAttachment(5000)

    dcMotor0.setTargetVelocity(1)

    try:
        input("Press Enter to Stop\n")
    except (Exception, KeyboardInterrupt):
        pass

    dcMotor0.close()
    encoder0.close()


main()
