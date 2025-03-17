from Phidget22.Phidget import PhidgetException
from Phidget22.Devices.DCMotor import DCMotor
from Phidget22.Devices.Encoder import Encoder
import time
import threading
import collections

class PIDController:
    """
    A class to represent a PID controller.

    Attributes:
    -----------
    kp : float
        Proportional gain.
    ki : float
        Integral gain.
    kd : float
        Derivative gain.
    dt : float
        Time step.
    integral : float
        Accumulated integral of the error.
    prev_error : float
        Previous error value.
    transfer_function : ctrl.TransferFunction
        The transfer function of the PID controller of the 
        form C(s) = Kd*s + Kp + Ki/s.
    integral_contribution_limit : float
        The contribution limit of the integral term to the output.
    """
    def __init__(self, kp: float, ki: float, kd: float, dt: float, integral_contribution_limit: float = 1.0):
        """
        Initializes the PID controller with attributes 
        integral and prev_error set to 0.

        Parameters:
        -----------
        kp : float
            Proportional gain.
        ki : float
            Integral gain.
        kd : float
            Derivative gain.
        dt : float
            Time step.
        integral_contribution_limit : float
            The contribution limit of the integral term to the output.
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self.integral = 0
        self.prev_error = 0
        self.integral_contribution_limit = integral_contribution_limit
        self.transfer_function = ctrl.TransferFunction([self.kd, self.kp, self.ki], [1, 0])
        self.integral_clamping_enabled = True

    def update(self, measurement: float, setpoint: float) -> float:
        """
        Updates the PID controller.
        
        Parameters:
        -----------
        measurement : float
            The current measurement of the system.
        setpoint : float
            The desired set value of the system.
        
        Returns:
        --------
        float
            The output of the PID controller.

        Functionality:
        --------
        This method calculates the error, updates the 
        integral and derivative terms, and computes the 
        control output.
        """
        error = setpoint - measurement
        
        # Calculate derivative term
        derivative = (error - self.prev_error) / self.dt
        
        output = self.kp * error + self.kd * derivative

        # Add the integral term
        if self.ki != 0:
            # Update integral term with anti-windup clamping
            self.integral += error * self.dt
            self.integral_contribution = self.ki * self.integral
            if self.integral_clamping_enabled:
                # Clamp the integral contribution to the specified limit
                if self.integral_contribution > self.integral_contribution_limit:
                    self.integral_contribution = self.integral_contribution_limit
                elif self.integral_contribution < -self.integral_contribution_limit:
                    self.integral_contribution = -self.integral_contribution_limit
            # Back-calculate the integral error
            self.integral = self.integral_contribution / self.ki
            output += self.integral_contribution
        
        # Update previous error
        self.prev_error = error
        
        return output

    def get_tf(self):
        """
        Returns the transfer function of the PID controller.
        """
        return self.transfer_function

    def reset(self):
        """
        Resets the integral term and previous error.
        """
        self.integral = 0
        self.integral_contribution = 0
        self.prev_error = 0
        self.enable_integral_clamping()

    def set_integral_contribution_limit(self, integral_contribution_limit):
        """
        Sets the limit of the contribution of the integral term to the output.
        """
        self.integral_contribution_limit = integral_contribution_limit

    def disable_integral_clamping(self):
        """
        Disables the integral clamping.
        """
        self.integral_clamping_enabled = False

    def enable_integral_clamping(self):
        """
        Enables the integral clamping.
        """
        self.integral_clamping_enabled = True

class SpeedSensor:
    def __init__(self, buffer_size=10,sampling_interval=50):
        self.buffer_size = buffer_size
        self.ring_buffer = collections.deque(maxlen=buffer_size)
        self.encoder = Encoder()
        self.encoder.setOnPositionChangeHandler(self.onPositionChange)
        self.encoder.setDataInterval(sampling_interval)

    def onPositionChange(self, encoder, positionChange, timeChange, indexTriggered):
            """Callback function to handle position changes."""
            # Calculate current speed from position change (position change over time)
            # print(positionChange, timeChange)
            # print(f"Current Speed: {self.current_speed}, Target Speed: {self.target_speed}, Motor Output: {self.motor_speed}")
            self.current_speed = positionChange / timeChange * 1000 if timeChange != 0 else 0
            self.ring_buffer.append(self.current_speed)

    def get_speed(self):
        return sum(self.ring_buffer) / len(self.ring_buffer)

class Motor:
    def __init__(self):
        # Initialize devices
        self.dcMotor = DCMotor()
        self.dcMotor.openWaitForAttachment(5000)
        self.dcMotor.setAcceleration(3)
        self.encoder.openWaitForAttachment(5000)
        self.set_data_interval()

    def set_speed(self, speed: float):
        """Sets the target speed."""
        # Clip speed to be within -1 to 1
        clipped_speed = max(min(speed, 1), -1)
        self.dcMotor.setTargetVelocity(clipped_speed)
        
    def stop(self):
        """Stops the motor."""
        self.set_speed(0)

    def close(self):
        """Closes the devices."""
        self.stop()
        self.dcMotor.close()
