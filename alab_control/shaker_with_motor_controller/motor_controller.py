import datetime
from typing import List, Tuple
from Phidget22.Phidget import PhidgetException
from Phidget22.Devices.DCMotor import DCMotor
from Phidget22.Devices.Encoder import Encoder
import control as ctrl
import time
import threading
import collections
import numpy as np
from matplotlib import pyplot as plt
from scipy.signal import find_peaks

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
    get_output_unit():
        Returns the unit of the output.
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

    def get_output_unit(self) -> str:
        """
        Returns the unit of the output.
        """
        return "Unitless (scaled current)"

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
    running : bool
        Indicates whether the sensor is currently running.

    Methods
    -------
    start():
        Initializes the sensor.
    stop():
        Stops the sensor.
    read_PV():
        Returns the process variable (PV) value, which is the speed.
    read_control_PV():
        Returns the scaled (control) PV value.
    get_PV_unit():
        Returns the unit of the speed.
    scale_to_control(speed):
        Scales the given speed to the control range [0, 1].
    scale_to_actual(control_speed):
        Scales the control speed to the actual speed range.
    set_minimum_measurable_speed(minimum_measurable_speed):
        Sets the minimum measurable speed of the sensor.
    set_maximum_measurable_speed(maximum_measurable_speed):
        Sets the maximum measurable speed of the sensor.
    _onPositionChange(encoder, positionChange, timeChange, indexTriggered):
        Callback function to handle position changes and 
        calculate the current speed.
    _get_speed():
        Returns the average speed based on the values in 
        the ring buffer.
    """
    def __init__(self, buffer_size: int = 5, sampling_interval: int = 50,
                 minimum_measurable_speed: float = 0.0, maximum_measurable_speed: float = 50.0):
        """
        Initializes the SpeedSensor with the given buffer 
        size, sampling interval, and speed range.

        Parameters
        ----------
        buffer_size : int, optional
            The size of the ring buffer used to store recent 
            speed measurements (default is 5).
        sampling_interval : int, optional
            The interval in milliseconds at which the encoder 
            data is sampled (default is 50).
        minimum_measurable_speed : float, optional
            The minimum speed that the sensor can measure (default is 0.0).
        maximum_measurable_speed : float, optional
            The maximum speed that the sensor can measure (default is 50.0).
        """
        self.buffer_size = buffer_size
        self.ring_buffer = collections.deque(maxlen=buffer_size)
        self.current_speed = 0.0
        self.sampling_interval = sampling_interval
        self.minimum_measurable_speed = minimum_measurable_speed
        self.maximum_measurable_speed = maximum_measurable_speed
        self.encoder = Encoder()
        self.encoder.setOnPositionChangeHandler(self._onPositionChange)
        self.running = False

    def start(self) -> None:
        """
        Starts the sensor.
        """
        self.encoder.openWaitForAttachment(5000)
        self.encoder.setDataInterval(self.sampling_interval)
        self.running = True

    def stop(self) -> None:
        """
        Stops the sensor.
        """
        self.running = False

    def read_PV(self) -> float:
        """
        Returns the process variable (PV) value, which is 
        the
        speed.
        """
        return self._get_speed()
    
    def read_control_PV(self) -> float:
        """
        Returns the scaled (control) PV value.
        """
        return self.scale_to_control(self._get_speed())
        
    def get_PV_unit(self) -> str:
        """
        Returns the unit of the speed.
        """
        return "Pulse/s"

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

    def _onPositionChange(self, encoder, positionChange: float, timeChange: float, indexTriggered: bool) -> None:
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
        self.current_speed = (positionChange / timeChange) * 1000 if timeChange != 0 else 0
        self.ring_buffer.append(self.current_speed)

    def _get_speed(self) -> float:
        """
        Returns the average speed based on the values in 
        the ring buffer.
        """
        if not self.ring_buffer:
            return 0.0
        return sum(self.ring_buffer) / len(self.ring_buffer)

class DiscretePlant:
    """
    A class to represent a discrete plant with a sensor and 
    an actuator, providing methods to control and monitor 
    the plant's behavior.

    This class models a discrete plant that requires a 
    sensor and an actuator to operate. The sensor is 
    responsible for measuring the process variable (PV) and 
    providing a scaled (control) PV for control purposes. 
    The actuator is responsible for adjusting the control 
    output to influence the PV. The class includes methods
    for starting and stopping the plant, setting control 
    outputs, obtaining step responses, and tuning the 
    control parameters.

    Attributes
    ----------
    sensor : SpeedSensor
        The sensor object used to measure the process 
        variable.
    actuator : Motor
        The actuator object used to control the process 
        variable.
    dt : float
        The time step for the discrete plant.
    plant_tf : ctrl.TransferFunction, optional
        The transfer function of the plant, default is 
        None.

    Methods
    -------
    step_response(duration: float) -> Tuple[np.ndarray, List[float]]
        Returns the step response of the plant over the 
        specified duration.
    start() -> None
        Starts the plant by starting the sensor and 
        actuator at 0 control output.
    start_sensor() -> None
        Starts only the sensor.
    stop() -> None
        Stops both the sensor and the actuator.
    stop_actuator() -> None
        Stops only the actuator.
    stop_sensor() -> None
        Stops only the sensor.
    set_control_output(output: float) -> None
        Sets the control output of the plant, scaled to the 
        actual output range of the actuator.
    get_control_PV() -> float
        Returns the scaled (control) PV of the plant.
    set_characteristics(order: str = "First", 
                        *args, 
                        **kwargs) -> None
        Sets the characteristics of the plant.
        Currently only supports first and second-order
        systems.
    get_tf() -> ctrl.TransferFunction
        Returns the transfer function of the plant.
    get_minimum_output_rise_time() -> float
        Returns the rise time of the plant to reach the 
        minimum output.
    """
    def __init__(self, sensor: SpeedSensor, 
                 actuator: Motor,
                 dt: float):
        """
        Initializes the DiscretePlant with the given 
        sensor, actuator, and time step.

        Parameters
        ----------
        sensor : SpeedSensor
            The sensor object used to measure the process 
            variable (PV).
        actuator : Motor
            The actuator object used to control the process
            variable.
        dt : float
            The time step for the discrete plant.

        Raises
        ------
        ValueError
            If the sensor or actuator does not have the 
            required methods and attributes.
        """
        self.sensor = sensor
        # check if the sensor have a start method
        if not hasattr(self.sensor, 'start'):
            raise ValueError("Sensor must have a start method.")
        # check if the sensor have a running attribute
        if not hasattr(self.sensor, 'running'):
            raise ValueError("Sensor must have a running attribute.")
        # check if the sensor have a stop method
        if not hasattr(self.sensor, 'stop'):
            raise ValueError("Sensor must have a stop method.")
        # check if the sensor have a read_PV method
        if not hasattr(self.sensor, 'read_PV'):
            raise ValueError("Sensor must have a read_PV method.")
        # check if the sensor have a read_control_PV method
        if not hasattr(self.sensor, 'read_control_PV'):
            raise ValueError("Sensor must have a read_control_PV method.")
        # check if the sensor have a scale_to_control method
        if not hasattr(self.sensor, 'scale_to_control'):
            raise ValueError("Sensor must have a scale_to_control method.")
        # check if the sensor have a scale_to_actual method
        if not hasattr(self.sensor, 'scale_to_actual'):
            raise ValueError("Sensor must have a scale_to_actual method.")
        # check if the sensor have a get_PV_unit method
        if not hasattr(self.sensor, 'get_PV_unit'):
            raise ValueError("Sensor must have a get_PV_unit method.")
        self.actuator = actuator
        # check if the actuator have a set_output method
        if not hasattr(self.actuator, 'set_control_output'):
            raise ValueError("Actuator must have a set_output method.")
        # check if the actuator have a start method
        if not hasattr(self.actuator, 'start'):
            raise ValueError("Actuator must have a start method.")
        # check if the actuator have a running attribute
        if not hasattr(self.actuator, 'running'):
            raise ValueError("Actuator must have a running attribute.")
        # check if the actuator have a stop method
        if not hasattr(self.actuator, 'stop'):
            raise ValueError("Actuator must have a stop method.")
        # check if the actuator have a scale_to_control method
        if not hasattr(self.actuator, 'scale_to_control'):
            raise ValueError("Actuator must have a scale_to_control method.")
        # check if the actuator have a scale_to_actual method
        if not hasattr(self.actuator, 'scale_to_actual'):
            raise ValueError("Actuator must have a scale_to_actual method.")
        # check if the actuator have a get_output_unit method
        if not hasattr(self.actuator, 'get_output_unit'):
            raise ValueError("Actuator must have a get_output_unit method.")
        self.dt = dt
        self.plant_tf = None

    def step_response(self, duration: float) -> Tuple[np.ndarray, List[float]]:
        """
        Returns the step response of the plant.
        """
        self.start()
        self.set_control_output(0)
        t = np.linspace(0, duration, int(duration/self.dt))
        y = []
        previous_time = time.time()
        for i in range(len(t)):
            time_stepped = False
            while not time_stepped:
                if time.time() - previous_time >= self.dt:
                    time_stepped = True
                    previous_time = time.time()
                    self.set_control_output(1)
                    y.append(self.get_control_PV())
                else:
                    time.sleep(self.dt/10000)
        self.stop()
        
        return t, y
    
    def start(self) -> None:
        """
        Starts the plant. Actuator is started at 0 control 
        output. This does not mean that the actuator is 
        off, it is just at the minimum output where it can 
        have an effect on the PV.
        """
        self.sensor.start()
        self.actuator.start()
        self.set_control_output(0)

    def start_sensor(self) -> None:
        """
        Starts only the sensor.
        """
        self.sensor.start()

    def stop(self) -> None:
        """
        Stops the actuator and the sensor.
        """
        self.sensor.stop()
        self.actuator.stop()
    
    def stop_actuator(self) -> None:
        """
        Stops only the actuator.
        """
        self.actuator.stop()

    def stop_sensor(self) -> None:
        """
        Stops only the sensor.
        """
        self.sensor.stop()

    def set_control_output(self, output: float) -> None:
        """
        Sets the control output of the plant.
        The output is scaled to the actual output range of the actuator.
        The output is clipped to the range [0, 1].
        If the output is less than 0, it is set to 0.
        If the output is greater than 1, it is set to 1.
        """
        # Clip the output to the range [0, 1]
        output = max(0, min(output, 1))
        self.actuator.set_control_output(output)

    def get_control_PV(self) -> float:
        """
        Returns the scaled (control) PV of the plant.
        """
        return self.sensor.read_control_PV()
            
    def set_characteristics(self, 
                            order: str = "Second", 
                            *args, 
                            **kwargs) -> None:
        """
        Sets the characteristics of the plant.
        Currently only supports first and second-order systems.
        """
        if order == "First":
            K, tau = args
            self.plant_tf = ctrl.TransferFunction([K], [tau, 1])
        elif order == "Second":
            K, zeta, wn = args
            self.plant_tf = ctrl.TransferFunction([K * wn**2], [1, 2 * zeta * wn, wn**2])
        else:
            raise ValueError("Unsupported order. Only first-order systems are supported.")
    
    def get_tf(self) -> ctrl.TransferFunction:
        """
        Returns the transfer function of the plant.
        """
        return self.plant_tf
    
    def get_time_to_steady_state(self, 
                                 output: float, 
                                 steady_state_wait_duration: float = 5,
                                 error_limit: float = 0.01, 
                                 max_time: float = 40, 
                                 cooldown_time: float = 20, 
                                 stop_sensor_after_steady_state: bool = True) -> Tuple[float, float, np.ndarray, np.ndarray, bool]:
        """
        Get the time it takes for the plant to reach 
        steady-state temperature.

        Parameters
        ----------
        output : float
            The output of the plant. can be between 0 and 
            1.
        steady_state_wait_duration : float
            The duration to wait for the plant to reach 
            steady state.
        error : float
            The steady state error in the control PV.
        max_time : float
            The maximum time to wait for the plant to reach 
            steady-state.
        cooldown_time : float
            The time to wait after each test to cool down 
            the plant.
        stop_sensor_after_steady_state : bool
            Whether to stop the sensor after the plant 
            reaches steady-state.

        Returns
        -------
        float
            The time it takes to reach steady state.
        float
            The steady state temperature.
        array
            The time points.
        array
            The temperature values.
        bool
            Whether the plant is not getting any PV change.
        """
        self.start()
        self.set_control_output(0)
        start_time = time.time()
        previous_time = time.time()
        steady_state=False
        no_PV=True
        t=[]
        y=[]
        while (no_PV or not steady_state) and time.time() - start_time < max_time:
            no_PV = True
            steady_state = False
            time_stepped = False
            while not time_stepped:
                if time.time() - previous_time >= self.dt:
                    time_stepped = True
                    previous_time = time.time()
                    self.set_control_output(output)
                    t.append(time.time())
                    y.append(self.get_control_PV())
                    # check all values of temperature for the last steady_state_wait seconds
                    if len(y) > int(steady_state_wait_duration // self.dt):
                        y_diff = max(y[-int(steady_state_wait_duration // self.dt):]) - min(y[-int(steady_state_wait_duration // self.dt):])
                        if abs(y_diff) < error_limit:
                            steady_state = True
                        if y[-1] > error_limit:
                            no_PV = False
                else:
                    time.sleep(self.dt/10000)
        self.stop_actuator()
        if stop_sensor_after_steady_state:
            self.stop_sensor()
        t=np.array(t)
        y=np.array(y)
        t=t-t[0]
        # return the time it takes to reach steady state and the steady state temperature
        t_steady = t[-1]
        y_steady = y[-1]
        if not steady_state:
            ValueError("System is not reaching steady-state after maximum test time. Try increasing the maximum test time.")
        time.sleep(cooldown_time)
        return t_steady, y_steady, t, y, no_PV
    
class PIDTuner:
    """
    This class is designed to tune PID controllers for 
    first-order systems, such as a Joule Heater with a 
    small sample mass. 
    
    This class does not consider sensor transfer functions 
    and assumes that the sensor is ideal (H(s) = 1), i.e. 
    no measurement error or noise, infinite bandwidth, 
    linearity, and no drift.
    
    This class only considers specific forms of controller 
    and plant transfer functions. Specifically, this class
    only consider controller transfer functions of the 
    form: C(s) = Kp + Ki/s + Kd*s (transfer function of the
    PID controller) and plant transfer functions of the 
    form: P(s) = K/(tau*s + 1) (first-order system with 
    time constatn tau and gain K).

    Attributes
    ----------
        dt (float): The time step for the discrete system.
        plant (DiscretePlant): The plant model to be 
            controlled.
        Kp_test_setting (dict[str, float]): Settings for 
            testing the proportional gain (Kp). Key value
            pairs include:
            - 'initial_Kp' (float): Initial proportional 
               gain.
            - 'Kp_increment' (float): Increment for 
               proportional gain during testing.
            - 'max_Kp' (float): Maximum proportional gain 
               for testing.
        ss_test_setting (dict[str, float]): Settings for 
            steady-state test. Key value pairs include:
            - 'maximum_time' (float): Maximum time for the 
               test.
            - 'error_limit' (float): Error limit for steady-
               state detection.
            - 'cooldown_time' (float): Cooldown time 
               between tests.
        osc_test_setting (dict[str, float]): Settings for 
            oscillation test. Key value pairs include:
            - 'initial_time' (float): Initial time for the 
               oscillation test.
            - 'time_increment' (float): Time increment for 
               the oscillation test.
            - 'maximum_time' (float): Maximum time for the 
               oscillation test.
            - 'cooldown_time' (float): Cooldown time 
               between tests.
            - 'minimum_oscillation_height' (float): Minimum 
               height of oscillations to be considered 
               sustained.
        Ku (float or None): Ultimate gain for the PID 
            controller.
        Pu (float or None): Oscillation period for the PID 
            controller.
        open_loop_tf (ctrl.TransferFunction or None): Open-
            loop transfer function of the system.
        closed_loop_tf (ctrl.TransferFunction or None): 
            Closed-loop transfer function of the system.
        controller (PIDController or None): The PID 
            controller being tuned.

    Methods:
    ----------
        compute_open_loop_tf() -> None:
            Computes the open-loop transfer function of the 
            plant with the PID controller.
        
        compute_closed_loop_tf() -> None:
            Computes the closed-loop transfer function of 
            the plant with the PID controller.
        
        find_system_parameters() -> None:
            Finds the system gain (K) and time constant 
            (tau) from the step response.
        
        determine_ultimate_gain_and_period() -> tuple[float, float]:
            Automatically finds the ultimate gain (Ku) and 
            oscillation period (Pu).
        
        check_poles() -> None:
            Computes and prints the poles of the closed-
            loop transfer function.
        
        find_ultimate_gain() -> tuple[float, float]:
            Automatically finds the ultimate gain (Ku) and 
            oscillation period (Pu).

        compute_pid_parameters(tuning_type: str = "Classic") -> None:
            Computes PID parameters using Ziegler-Nichols 
            tuning rules.

        stability_analysis() -> None:
            Performs stability analysis of the system 
            transfer function.

        def compute_tf() -> None:
            Computes the open-loop and closed-loop transfer 
            functions of the plant with the PID controller.

        tune() -> None:
            Finds the system parameters, ultimate gain, 
            computes PID parameters, computes transfer 
            functions and performs stability analysis.

        step_response(duration: float) -> tuple[np.ndarray, np.ndarray]:
            Returns the step response of the plant with the 
            tuned PID controller.

        get_controller() -> PIDController:
            Returns the tuned PID controller.
        """
    def __init__(self, 
                 plant: DiscretePlant,
                 dt: float = 0.5,
                 Kp_test_setting: dict[str, float] = {"initial_Kp": 12,"Kp_increment": 3,"max_Kp": 40},
                 ss_test_setting: dict[str, float] = {'steady_state_wait_duration': 5, 'maximum_time': 100, 'error_limit': 0.01, 'cooldown_time': 20},
                 osc_test_setting: dict[str, float]= {'initial_time': 20, 'time_increment': 20, 'maximum_time': 50, 'cooldown_time': 20, "minimum_oscillation_height": 0.01}):
        """
        Initializes the PIDTuner with the given plant, time 
        step, and test settings.

        Parameters
        ----------
        plant : DiscretePlant
            The plant model to be controlled.
        dt : float, optional
            The time step for the discrete system. Default 
            is 0.5.
        Kp_test_setting : dict[str, float], optional
            Settings for testing the proportional gain 
            (Kp). Default is {"initial_Kp": 7, "Kp_increment": 3, "max_Kp": 30}.
            Key value pairs include:
            - 'initial_Kp' (float): Initial proportional
               gain.
            - 'Kp_increment' (float): Increment for 
               proportional gain during testing.
            - 'max_Kp' (float): Maximum proportional gain 
               for testing.
        ss_test_setting : dict[str, float], optional
            Settings for steady-state test. Default is 
            {'maximum_time': 100, 'error_limit': 0.01, 'cooldown_time': 20}.
            Key value pairs include:
            - 'maximum_time' (float): Maximum time for the 
               test.
            - 'error_limit' (float): Error limit for 
               steady-state detection.
            - 'cooldown_time' (float): Cooldown time 
               between tests.
        osc_test_setting : dict[str, float], optional
            Settings for oscillation test. Default is 
            {'initial_time': 20, 'time_increment': 20, 'maximum_time': 100, 'cooldown_time': 20, "minimum_oscillation_height": 0.025}.
            Key value pairs include:
            - 'initial_time' (float): Initial time for the 
               oscillation test.
            - 'time_increment' (float): Time increment for 
               the oscillation test.
            - 'maximum_time' (float): Maximum time for the 
               oscillation test.
            - 'cooldown_time' (float): Cooldown time 
               between tests.
            - 'minimum_oscillation_height' (float): Minimum 
               height of oscillations to be considered 
               sustained.

        Raises
        ------
        ValueError
            If the plant does not have a step_response 
            method.
        """
        self.dt = dt
        self.plant = plant
        # check if the process has a step_response method
        if not hasattr(self.plant, 'step_response'):
            raise ValueError("Process must have a step_response method.")
        self.Kp_test_setting = Kp_test_setting
        self.ss_test_setting = ss_test_setting
        self.osc_test_setting = osc_test_setting
        self.Ku = None
        self.Pu = None
        self.open_loop_tf = None
        self.closed_loop_tf = None
        self.controller = None

    def find_system_parameters(self) -> None:
        """
        Finds the system parameters (gain, time constant, 
        and damping ratio) from the step response. Supports 
        both first-order and second-order systems.

        Raises:
            ValueError: If the minimum or maximum output of 
                        the plant has not been tuned.
            ValueError: If the system is not getting any PV
                        change from 0.

        Returns:
            None
        """
        print("Finding system parameters using grid search...")
        steady_state_wait_duration = self.ss_test_setting['steady_state_wait_duration']
        maximum_time = self.ss_test_setting['maximum_time']
        error_limit = self.ss_test_setting['error_limit']
        cooldown_time = self.ss_test_setting['cooldown_time']
        print(f"Maximum time for the test: {maximum_time} seconds")
        print("Date and time: ", datetime.datetime.now())
        # check if plant has been tuned for minimum and maximum output
        if not self.plant.minimum_output_tuned:
            raise ValueError("Minimum output of the plant must be tuned first. Run tune_minimum_output_and_PV method.")
        if not self.plant.maximum_output_tuned:
            raise ValueError("Maximum output of the plant must be tuned first. Run tune_maximum_output_and_PV method.")
        t_steady, y_steady, t, y, no_PV = self.plant.get_time_to_steady_state(1, steady_state_wait_duration=steady_state_wait_duration, error_limit=error_limit, max_time=maximum_time, cooldown_time=cooldown_time)
        if no_PV:
            raise ValueError("System is not getting any PV change from 0. Check the system.")
        
        K = y[-1]  # Gain is the final value of the step response
        threshold = 0.632 * K  # 63.2% of the final value for first-order systems
        tau = None
        zeta = None
        wn = None

        # Check if the system is first-order or second-order
        overshoot = (max(y) - K) / K if K > 0 else 0
        if overshoot < 0.05:  # Consider it a first-order system if overshoot is negligible
            for i in range(len(y)):
                if y[i] >= threshold:
                    tau = t[i]
                    break
            self.plant.set_characteristics("First", K, tau)
        else:  # Second-order system
            # Calculate damping ratio (zeta) and natural frequency (wn) from overshoot and rise time
            zeta = -np.log(overshoot) / np.sqrt(np.pi**2 + (np.log(overshoot))**2)
            rise_time_index = next(i for i in range(len(y)) if y[i] >= K * 0.9)  # 90% of final value
            rise_time = t[rise_time_index]
            wn = np.pi / (rise_time * np.sqrt(1 - zeta**2))
            self.plant.set_characteristics("Second", K, zeta, wn)

    def find_ultimate_gain(self) -> tuple[float, float]:
        """
        Automatically finds the ultimate gain (Ku) and 
        oscillation period (Pu).
        
        This method uses a grid search approach to 
        determine the ultimate gain and period by 
        iteratively adjusting the proportional gain (Kp) 
        and observing the system's response.

        Raises:
            AssertionError: If the time step (dt) of the 
                            plant and the controller do not 
                            match.
            ValueError: If the ultimate gain (Ku) and 
                        period (Pu) could not be determined.

        Returns:
            tuple: A tuple containing the ultimate gain 
            (Ku) and oscillation period (Pu).
        """
        assert self.dt==self.plant.dt, "The plant and the controller must have the same time step."
        print("Finding ultimate gain and period using grid search...")
        maximum_time = 0
        test_time = self.osc_test_setting['initial_time']
        for _ in range(int(self.osc_test_setting['initial_time']), int(self.osc_test_setting['maximum_time']), int(self.osc_test_setting['time_increment'])):
            maximum_time += test_time
            test_time = test_time + self.osc_test_setting['time_increment'] * len(np.arange(self.Kp_test_setting['initial_Kp'], self.Kp_test_setting['max_Kp'], self.Kp_test_setting['Kp_increment']))
        print(f"Maximum time for the test: {maximum_time} seconds")
        print("Date and time: ", datetime.datetime.now())
        sustained_oscillation_detected = False
        for duration in range(int(self.osc_test_setting['initial_time']), int(self.osc_test_setting['maximum_time']) + 1, int(self.osc_test_setting['time_increment'])):
            for Kp in np.arange(self.Kp_test_setting['initial_Kp'], self.Kp_test_setting['max_Kp'], self.Kp_test_setting['Kp_increment']):
                self.p_controller = PIDController(Kp, 0, 0, self.dt)
                self.plant.start()
                self.plant.set_control_output(0)
                t = np.linspace(0, duration, int(duration / self.dt))
                y = []
                previous_time = time.time()
                for _ in range(len(t)):
                    time_stepped = False
                    while not time_stepped:
                        if time.time() - previous_time >= self.dt:
                            time_stepped = True
                            previous_time = time.time()
                            self.plant.set_control_output(
                                self.p_controller.update(self.plant.get_control_PV(), 0.5)
                            )  # set the setpoint to 0.5
                            y.append(self.plant.get_control_PV())
                        else:
                            time.sleep(self.dt / 10000)
                self.plant.stop()
                y = np.array(y)
                # Find peaks and valleys
                peaks, _ = find_peaks(y)
                valleys, _ = find_peaks(-y)
                # From peaks and valleys, calculate the average of the peak and valley values
                peak_valley_avg = None
                if len(peaks) > 5 and len(valleys) > 5:
                    for i in range(min(len(peaks), len(valleys))):
                        if peak_valley_avg is None:
                            peak_valley_avg = (y[peaks[i]] + y[valleys[i]]) / 2
                        else:
                            peak_valley_avg = (peak_valley_avg + ((y[peaks[i]] + y[valleys[i]]) / 2)) / 2
                # From the average peak and valley values, calculate the amplitude of the oscillation
                if peak_valley_avg:
                    oscillation_amplitudes = [abs(peak_valley_avg - y[peak]) for peak in peaks]
                    # If sustained oscillations detected, calculate Ku and Pu
                    if all(amp > self.osc_test_setting["minimum_oscillation_height"] for amp in oscillation_amplitudes):
                        self.Pu = np.mean(np.diff(t[peaks]))  # Average period
                        self.Ku = Kp
                        sustained_oscillation_detected = True
                        break
                time.sleep(self.osc_test_setting['cooldown_time'])  # Cooldown time between tests
            if sustained_oscillation_detected:
                break
        if not self.Ku:
            raise ValueError("Ultimate gain (Ku) and period (Pu) could not be determined.")
        return self.Ku, self.Pu

    def compute_pid_parameters(self, tuning_type: str = "Custom") -> None:
        """
        Computes PID parameters using Ziegler-Nichols 
        tuning rules.
        """
        if self.Ku and self.Pu:
            if tuning_type=="Classic":
                self.Kp = 0.6 * self.Ku
                Ti = self.Pu / 2
                Td = self.Pu / 8
            elif tuning_type=="Some_overshoot":
                self.Kp = self.Ku / 3
                Ti = self.Pu / 2
                Td = self.Pu / 3
            elif tuning_type=="No_overshoot":
                self.Kp = self.Ku * 0.2
                Ti = self.Pu / 2
                Td = self.Pu / 3
            elif tuning_type=="PI":
                self.Kp = self.Ku * 0.45
                Ti = self.Pu / 1.2
                Td = 0
            elif tuning_type=="Custom":
                self.Kp = self.Ku * 0.2
                Ti = self.Pu / 2
                Td = self.Pu / 100
            else:
                raise ValueError("tuning_type must be one of 'Classic', 'Some_overshoot', 'No_overshoot','PI'")
            self.Ki = self.Kp / Ti
            self.Kd = self.Kp * Td
        else:
            raise ValueError("Ultimate gain (Ku) and period (Pu) must be determined first.")
        if self.controller:
            integral_contribution_limit = self.controller.integral_contribution_limit
            self.controller = PIDController(self.Kp, self.Ki, self.Kd, self.dt, integral_contribution_limit)
        else:
            self.controller = PIDController(self.Kp, self.Ki, self.Kd, self.dt) # use default integral_contribution_limit if PIDController is not initialized yet
        
    def _poles_check(self, closed_loop_system: ctrl.TransferFunction) -> None:
        """
        Check if the system is unstable by checking if any 
        pole is in the right-half plane.
        """
        poles = ctrl.poles(closed_loop_system)
        unstable_poles = [p for p in poles if np.real(p) > 0]
        # plot poles
        plt.figure()
        plt.scatter(np.real(poles), np.imag(poles), color='red', marker='x')
        plt.axhline(0, color='black', lw=0.5)
        plt.axvline(0, color='black', lw=0.5)
        plt.xlabel('Real')
        plt.ylabel('Imaginary')
        plt.title('Poles of the Closed Loop System')
        plt.show()
        if unstable_poles:
            print("⚠️ WARNING: System is UNSTABLE (Right-half plane poles detected).")
        else:
            print("✅ Poles check: OK. System is STABLE. No right-half plane poles detected.")

    def _nyquist_plot_check(self, open_loop_system: ctrl.TransferFunction) -> None:
        """
        Performs Nyquist plot analysis and checks for stability.
        How many right half plane zeros are there in the C*G transfer function? Which will be poles in the closed loop system.
        """
        response = ctrl.nyquist_response(open_loop_system)
        count = response.count
        cplt = response.plot()
        if count > 0:
            print("⚠️ WARNING: System is UNSTABLE (Nyquist plot CW encirclements of -1 detected).")
        else:
            print("✅ Nyquist plot check: OK. System is STABLE. No CW encirclements of -1 detected.")

    def _bode_plot_check(self, open_loop_system):
        """Performs Bode plot analysis and checks for stability margins."""
        plt.figure()
        ctrl.bode(open_loop_system, dB=True)
        plt.show()
        gm, pm, sm, wpc, wgc, wms = ctrl.stability_margins(open_loop_system)
        # Stability Warnings Based on Margins
        if gm < 6:
            print(f"⚠️ WARNING: Low Gain Margin (<6 dB =~ 4 in linear). System is prone to instability. Gain Margin: {gm:.2f}.")
        else:
            print(f"✅ Gain Margin Check: OK (Greater than 6 dB =~ 4 in linear). Gain Margin: {gm:.2f}.")

        if pm < 45:
            print(f"⚠️ WARNING: Low Phase Margin (<45°). System is prone to oscillations. Phase Margin: {pm:.2f}°.")
        else:
            print(f"✅ Phase Margin Check: OK (Greater than 45°). Phase Margin: {pm:.2f}°.")
        
        delay_margin = (pm/wgc) * (np.pi/180) # Phase margin in seconds
        if delay_margin < 2*self.dt:
            print(f"⚠️ WARNING: Phase delay margin is less than twice of the sampling/control time. System can become unstable. Delay Margin: {delay_margin:.2f} seconds.")
        else:
            print(f"✅ Phase Delay Margin Check: OK (Greater than the sampling/control time). Delay Margin: {delay_margin:.2f} seconds.")

    def stability_analysis(self) -> None:
        """
        Performs stability analysis on the system transfer 
        function and prints warnings based on results.
        """
        if not self.open_loop_tf:
            raise ValueError("Open-loop transfer function is not computed.")
        if not self.closed_loop_tf:
            raise ValueError("Closed-loop transfer function is not computed.")
        open_loop_tf = self.open_loop_tf
        closed_loop_tf = self.closed_loop_tf
        self._poles_check(closed_loop_tf)
        self._nyquist_plot_check(open_loop_tf)
        self._bode_plot_check(open_loop_tf)

    # From gain and tau (system characteristics) and Kp, Ki, Kd (controller parameters)
    # we can calculate the open-loop transfer function of the system
    def compute_tf(self) -> None:
        """
        Computes the open-loop and closed-loop transfer 
        functions of the plant with the PID controller.
        """
        controller_tf = self.controller.get_tf()
        plant_tf = self.plant.get_tf()
        self.open_loop_tf = controller_tf * plant_tf
        self.closed_loop_tf = 1 / (1 + self.open_loop_tf)

    # tune the PID controller and do stability analysis
    def tune(self) -> None:
        """
        Finds the system parameters, ultimate gain, 
        computes PID parameters, computes transfer 
        functions and performs stability analysis.
        """
        self.find_system_parameters()
        self.find_ultimate_gain()
        self.compute_pid_parameters()
        self.compute_tf()
        self.stability_analysis()

    # Try a step response with the tuned PID controller
    def step_response(self, duration) -> tuple[np.ndarray, np.ndarray]:
        """
        Returns the step response of the plant with the 
        tuned PID controller.
        """
        # check if controller is computed
        if not self.controller:
            raise ValueError("Controller is not computed.")
        # reset the PID controller
        self.controller.reset()
        self.plant.start()
        self.plant.set_control_output(0)
        t = np.linspace(0, duration, int(duration / self.dt))
        y = []
        previous_time = time.time()
        for _ in range(len(t)):
            time_stepped = False
            while not time_stepped:
                if time.time() - previous_time >= self.dt:
                    time_stepped = True
                    previous_time = time.time()
                    self.plant.set_control_output(
                        self.controller.update(self.plant.get_control_PV(), 0.5)
                    )  # set the setpoint to 0.5
                    y.append(self.plant.get_control_PV())
                else:
                    time.sleep(self.dt / 10000)
        self.plant.stop()
        return t, y
    
    def get_controller(self) -> PIDController:
        """
        Returns the tuned PID controller.
        """
        return self.controller

class DiscreteSetpointProfile:
    """
    Superclass for discrete setpoint profiles.

    Attributes
    ----------
    time_points : List | np.ndarray
        The time points at which setpoint values are 
        defined.
    setpoint_values : List | np.ndarray
        The setpoint values corresponding to the time 
        points.
    interpolated_time : numpy.ndarray
        The interpolated time points used for creating a 
        smooth profile.
    interpolated_setpoints : numpy.ndarray
        The interpolated setpoint values corresponding to 
        the interpolated time points.

    Methods
    -------
    get_setpoint(time: float) -> float
        Returns the setpoint at a given time.
    plot_profile() -> None
        Plots the setpoint profile.
    get_interpolated_profile() -> tuple[numpy.ndarray, numpy.ndarray]
        Returns the interpolated time points and setpoints.
    get_original_profile() -> tuple[List | np.ndarray, List | np.ndarray]
        Returns the original time points and setpoints.
    """
    def __init__(self, time_points: List | np.ndarray, setpoint_values: List | np.ndarray):
        """
        Initializes the DiscreteSetpointProfile with time points and setpoint values.

        Parameters
        ----------
        time_points : List | np.ndarray
            The time points at which setpoint values are defined.
        setpoint_values : List | np.ndarray
            The setpoint values corresponding to the time points.

        Raises
        ------
        ValueError
            If `time_points` and `setpoint_values` do not have the same length.
            If `time_points` are not in increasing order.
        """
        self.time_points = time_points
        self.setpoint_values = setpoint_values
        # check that time_points and setpoint_values have the same length
        if len(time_points) != len(setpoint_values):
            raise ValueError("time_points and setpoint_values must have the same length.")
        # check that time_points are in increasing order
        if not all(time_points[i] <= time_points[i+1] for i in range(len(time_points)-1)):
            for i in range(len(time_points)-1):
                if time_points[i] >= time_points[i+1]:
                    print(f"Time point {i+1} is less than or equal to time point {i}.")
            raise ValueError("time_points must be in increasing order.")
        self.interpolated_time = np.arange(time_points[0], time_points[-1]+np.min(np.diff(time_points)), np.min(np.diff(time_points)))
        self.interpolated_setpoints = np.interp(self.interpolated_time, time_points, setpoint_values)

    def get_setpoint(self, time: float) -> float:
        """
        Returns the setpoint at a given time in seconds.

        Parameters
        ----------
        time : float
            The time at which the setpoint is requested.

        Returns
        -------
        float
            The setpoint value at the given time. If the 
            time is less than the first time point, the 
            first setpoint is returned. If the time is 
            greater than the last time point, the last 
            setpoint is returned. Otherwise, the setpoint 
            is interpolated based on the given time.
        """
        if time < self.interpolated_time[0]:
            return self.setpoint_values[0]
        elif time > self.interpolated_time[-1]:
            return self.setpoint_values[-1]
        return np.interp(time, self.interpolated_time, self.interpolated_setpoints)
    
    def plot_profile(self) -> None:
        """
        Plots the setpoint profile.

        This method creates a plot of the setpoint profile, 
        showing both the original setpoint values at the 
        specified time points and the interpolated setpoint 
        values over time. The original setpoints are 
        displayed as red scatter points, and the 
        interpolated setpoints are displayed as a 
        continuous line.

        The plot includes labeled axes, a title, a legend,
        and a grid for better readability.
        """
        plt.figure(figsize=(10, 5))
        plt.plot(self.interpolated_time, self.interpolated_setpoints, label='Interpolated Setpoints')
        plt.scatter(self.time_points, self.setpoint_values, color='red', zorder=5, label='Original Setpoints')
        plt.xlabel('Time (s)')
        plt.ylabel('Setpoint')
        plt.title('Discrete Setpoint Profile')
        plt.legend()
        plt.grid(True)
        plt.show()

    def get_interpolated_profile(self) -> tuple[List | np.ndarray, List | np.ndarray]:
        """
        Returns the interpolated time points and setpoints.
        """
        return self.interpolated_time, self.interpolated_setpoints
    
    def get_original_profile(self) -> tuple[List | np.ndarray, List | np.ndarray]:
        """
        Returns the original time points and setpoints.
        """
        return self.time_points, self.setpoint_values
