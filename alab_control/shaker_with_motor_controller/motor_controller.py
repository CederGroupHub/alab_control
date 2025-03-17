from Phidget22.Phidget import PhidgetException
from Phidget22.Devices.DCMotor import DCMotor
from Phidget22.Devices.DigitalInput import DigitalInput
from Phidget22.Devices.Encoder import Encoder
import time

class MotorController:
    def __init__(self, p=1.0, i=0.1, d=0.01):
        # Initialize devices
        self.dcMotor = DCMotor()
        self.digitalInput = DigitalInput()
        self.encoder = Encoder()

        # Set the digital input channel
        self.digitalInput.setChannel(1)

        # PID constants
        self.p = p  # Proportional gain
        self.i = i  # Integral gain
        self.d = d  # Derivative gain

        # PID variables
        self.target_speed = 0  # Target speed (desired)
        self.prev_error = 0  # Previous error (used in derivative calculation)
        self.integral = 0  # Integral of the error (used in integral calculation)
        self.current_speed = 0  # Current speed based on position change

        # Set position change handler
        self.encoder.setOnPositionChangeHandler(self.onPositionChange)

    def onPositionChange(self, encoder, positionChange, timeChange, indexTriggered):
        """Callback function to handle position changes."""
        # Calculate current speed from position change (position change over time)
        print(positionChange, timeChange)
        self.current_speed = positionChange / timeChange * 1000 if timeChange != 0 else 0
        self.pid_control()

    def open(self):
        """Opens the devices."""
        try:
            self.dcMotor.openWaitForAttachment(5000)
            self.dcMotor.setAcceleration(62.5)
            self.digitalInput.openWaitForAttachment(5000)
            self.encoder.openWaitForAttachment(5000)
            self.encoder.setDataInterval(1000)

        except PhidgetException as e:
            print(f"Error opening devices: {e}")

    def set_speed(self, speed: float):
        """Sets the target speed."""
        if -100 <= speed <= 100:
            self.target_speed = speed
            print(f"Target motor speed set to {speed}")
        else:
            print("Speed must be between -100 and 100")

    def pid_control(self):
        """Adjusts motor speed based on PID control."""
        # Calculate error
        error = (self.target_speed - self.current_speed) / 100

        # Proportional term
        p_term = self.p * error

        # Integral term
        self.integral += error
        i_term = self.i * self.integral

        # Derivative term
        d_term = self.d * (error - self.prev_error)

        # Calculate the total PID output
        pid_output = p_term + i_term + d_term

        # Set the motor speed based on PID output (clamp to range [0, 1])
        motor_speed = max(min(pid_output, 1), 0)

        # Apply motor speed
        self.dcMotor.setTargetVelocity(motor_speed)

        # Update previous error
        self.prev_error = error

        print(f"Current Speed: {self.current_speed}, Target Speed: {self.target_speed}, Motor Output: {motor_speed}")

    def stop(self):
        """Stops the motor."""
        self.set_speed(0)

    def close(self):
        """Closes the devices."""
        self.stop()
        self.dcMotor.close()
        self.digitalInput.close()
        self.encoder.close()

def main():
    motor_controller = MotorController(p=1, i=0.01, d=0.01)

    # Open devices
    motor_controller.open()

    # Set motor target speed and start
    motor_controller.set_speed(30)

    try:
        while True:
            # Apply PID control to adjust motor speed
            motor_controller.pid_control()
            time.sleep(0.1)  # Adjust the control loop speed (sampling rate)

    except (Exception, KeyboardInterrupt):
        pass

    # Stop the motor and close devices
    motor_controller.stop()
    motor_controller.close()

# main()