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

class Motor:
    """
    A class to represent a motor, which controls a DC motor 
    and interacts with an encoder for speed control.

    This class manages the DC motor and encoder, allowing 
    for setting the motor speed, stopping the motor, and 
    closing the devices. It includes scaling methods to map the motor speed to a control range.

    Attributes
    ----------
    dcMotor : DCMotor
        An instance of the DCMotor class representing the 
        DC motor.
    minimum_output : float
        The minimum control speed.
    maximum_output : float
        The maximum control speed.
    running : bool
        Indicates whether the motor is currently 
        running.

    Methods
    -------
    start():
        Initializes the motor.
    stop():
        Stops the motor.
    set_minimum_output(minimum_output):
        Sets the minimum control speed.
    set_maximum_output(maximum_output):
        Sets the maximum control speed.
    set_control_output(output):
        Sets the output of the motor in the range 
        [0, 1], scaling it to the actual output range.
    scale_to_control(output):
        Scales a given output of the motor to the 
        control output range [0, 1].
    scale_to_actual(control_output):
        Scales a given control output in the range [0, 1] 
        to the actual duty cycle/s speed range.
    """
    def __init__(self, 
                 minimum_control_speed: float = 0, 
                 maximum_control_speed: float = 0.3):
        """
        Initializes the Motor with DC motor and encoder 
        devices.
        """
        self.minimum_control_speed = minimum_control_speed
        self.maximum_control_speed = maximum_control_speed
        self.running = False

    def set_speed(self, speed: float) -> None:
        """
        Sets the target speed of the motor.

        Parameters
        ----------
        speed : float
            The target speed, clipped to the range [0, 1].
        """
        clipped_speed = max(min(speed, 1), 0)
        self.dcMotor.setTargetVelocity(clipped_speed)

    def start(self) -> None:
        self.dcMotor = DCMotor()
        self.dcMotor.openWaitForAttachment(5000)
        self.dcMotor.setAcceleration(3)

    def stop(self) -> None:
        """
        Stops the motor.
        """
        self.set_speed(0)
        self.dcMotor.close()       

    def scale_to_control(self, speed: float) -> float:
        """
        Scales the given speed to the control range [0, 1].
        """
        scaled_speed = (speed - self.minimum_control_speed) / (self.maximum_control_speed - self.minimum_control_speed)
        if scaled_speed < 0.0:
            return 0.0
        elif scaled_speed > 1.0:
            return 1.0
        else:
            return scaled_speed

    def scale_to_actual(self, control_speed: float) -> float:
        """
        Scales the control speed to the actual speed range.
        """
        return control_speed * (self.maximum_control_speed - self.minimum_control_speed) + self.minimum_control_speed
    
    def set_control_output(self, output: float) -> None:
        """
        Sets the output of the motor in the range [0, 1], 
        scaling it to the actual output range.
        """
        actual_speed = self.scale_to_actual(output)
        self.set_speed(actual_speed)

class SpeedSensor:
    """
    A class to represent a speed sensor, which calculates
    the speed based on encoder position changes.

    The speed sensor uses an encoder to track position 
    changes and calculates the speed by dividing the 
    position change by the time change. It maintains a 
    ring buffer to store recent speed measurements, 
    allowing for a smoothed speed reading. It includes scaling methods to map the speed to a control range.

    Attributes
    ----------
    buffer_size : int
        The size of the ring buffer used to store recent 
        speed measurements.
    ring_buffer : collections.deque
        A deque (double-ended queue) used as a ring buffer 
        to store recent speed measurements.
    encoder : Encoder
        An instance of the Encoder class used to track 
        position changes.
    current_speed : float
        The current calculated speed.
    minimum_measurable_speed : float
        The minimum speed that the sensor can measure.
    maximum_measurable_speed : float
        The maximum speed that the sensor can measure.

    Methods
    -------
    onPositionChange(encoder, positionChange, timeChange, indexTriggered):
        Callback function to handle position changes and 
        calculate the current speed.
    get_speed():
        Returns the average speed based on the values in 
        the ring buffer.
    set_minimum_measurable_speed(minimum_measurable_speed):
        Sets the minimum measurable speed of the sensor.
    set_maximum_measurable_speed(maximum_measurable_speed):
        Sets the maximum measurable speed of the sensor.
    scale_to_control(speed):
        Scales the given speed to the control range [0, 1].
    scale_to_actual(control_speed):
        Scales the control speed to the actual speed range.
    get_speed_unit():
        Returns the unit of the speed.
    """
    def __init__(self, buffer_size: int = 10, sampling_interval: int = 50,
                 minimum_measurable_speed: float = 0.0, maximum_measurable_speed: float = 100.0):
        """
        Initializes the SpeedSensor with the given buffer 
        size, sampling interval, and speed range.

        Parameters
        ----------
        buffer_size : int, optional
            The size of the ring buffer used to store recent 
            speed measurements (default is 10).
        sampling_interval : int, optional
            The interval in milliseconds at which the encoder 
            data is sampled (default is 50).
        minimum_measurable_speed : float, optional
            The minimum speed that the sensor can measure (default is -100).
        maximum_measurable_speed : float, optional
            The maximum speed that the sensor can measure (default is 100).
        """
        self.buffer_size = buffer_size
        self.ring_buffer = collections.deque(maxlen=buffer_size)
        self.encoder = Encoder()
        self.encoder.setOnPositionChangeHandler(self.onPositionChange)
        self.encoder.setDataInterval(sampling_interval)
        self.current_speed = 0.0
        self.minimum_measurable_speed = minimum_measurable_speed
        self.maximum_measurable_speed = maximum_measurable_speed

    def onPositionChange(self, encoder, positionChange: float, timeChange: float, indexTriggered: bool) -> None:
        """
        Callback function to handle position changes and 
        calculate the current speed.

        Parameters
        ----------
        encoder : Encoder
            The encoder instance that triggered the event.
        positionChange : float
            The change in position.
        timeChange : float
            The change in time in milliseconds.
        indexTriggered : bool
            Indicates whether an index was triggered.
        """
        self.current_speed = positionChange / timeChange * 1000 if timeChange != 0 else 0
        self.ring_buffer.append(self.current_speed)

    def get_speed(self) -> float:
        """
        Returns the average speed based on the values in 
        the ring buffer.
        """
        if not self.ring_buffer:
            return 0.0
        return sum(self.ring_buffer) / len(self.ring_buffer)

    def set_minimum_measurable_speed(self, minimum_measurable_speed: float) -> None:
        """
        Sets the minimum measurable speed of the sensor.
        """
        self.minimum_measurable_speed = minimum_measurable_speed

    def set_maximum_measurable_speed(self, maximum_measurable_speed: float) -> None:
        """
        Sets the maximum measurable speed of the sensor.
        """
        self.maximum_measurable_speed = maximum_measurable_speed

    def scale_to_control(self, speed: float) -> float:
        """
        Scales the given speed to the control range [0, 1].
        """
        scaled_speed = (speed - self.minimum_measurable_speed) / (self.maximum_measurable_speed - self.minimum_measurable_speed)
        if scaled_speed < 0.0:
            return 0.0
        elif scaled_speed > 1.0:
            return 1.0
        else:
            return scaled_speed

    def scale_to_actual(self, control_speed: float) -> float:
        """
        Scales the control speed to the actual speed range.
        """
        return control_speed * (self.maximum_measurable_speed - self.minimum_measurable_speed) + self.minimum_measurable_speed

    def get_speed_unit(self) -> str:
        """
        Returns the unit of the speed.
        """
        return "units/ms" #Or whatever unit is appropriate.

