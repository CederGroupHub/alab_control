from typing import List, Tuple
from Phidget22.Phidget import PhidgetException
from Phidget22.Devices.DCMotor import DCMotor
from Phidget22.Devices.Encoder import Encoder
import control as ctrl
import time
import threading
import collections
import numpy as np

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

    Methods
    -------
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
        self.encoder = Encoder()
        self.encoder.setOnPositionChangeHandler(self._onPositionChange)
        self.encoder.setDataInterval(sampling_interval)
        self.current_speed = 0.0
        self.minimum_measurable_speed = minimum_measurable_speed
        self.maximum_measurable_speed = maximum_measurable_speed

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

    #TODO: check if this is working as expected with the PV_maximum_safety_limit
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

        # Hard safety from the temperature feedback loop. 
        # If the temperature from the sensor gets too hot, the actuator should be turned off.
        # Error should be raised and plant should be stopped.
        if self.get_control_PV() > self.PV_maximum_safety_limit:
            self.stop()
            raise ValueError("Temperature is too high. Plant is stopped.")
        self.actuator.set_control_output(output)

    def get_control_PV(self) -> float:
        """
        Returns the scaled (control) PV of the plant.
        """
        return self.sensor.read_control_PV()

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
    
    def tune_minimum_output_and_PV(self, 
                                   start_at: float = 0.2, 
                                   step_size: float = 0.1, 
                                   lower_threshold: float = 0.0025, 
                                   upper_threshold: float = 0.005,
                                   steady_state_wait_duration: float = 5, 
                                   error_limit: float = 0.01, 
                                   max_time: float = 40, 
                                   cooldown_time: float = 10, 
                                   max_total_time: float = 600) -> None:
        """
        Tunes the minimum output of the actuator where the 
        PV starts to increase.
        """
        if not self.minimum_output_tuned:
            start_time = time.time()
            # Iterate from start_at to 1
            steady_state_control_PV = 0
            minimum_output_found = False
            for output in np.arange(start_at, 1, step_size):
                t_steady, steady_state_control_PV, __, ___, ____ = self.get_time_to_steady_state(output, steady_state_wait_duration=steady_state_wait_duration, error_limit=error_limit, max_time=max_time, cooldown_time=cooldown_time)
                if steady_state_control_PV > upper_threshold:
                    minimum_output_found = True
                    break

            if not minimum_output_found:
                raise ValueError("Minimum output not found. System cannot reach the threshold.")
            
            # Perform binary search to find the minimum output
            while (steady_state_control_PV > upper_threshold or steady_state_control_PV < lower_threshold) and time.time() - start_time < max_total_time:
                if steady_state_control_PV > upper_threshold:
                    output -= step_size
                else:
                    output += step_size
                step_size /= 2
                t_steady, steady_state_control_PV, __, ___, ____ = self.get_time_to_steady_state(output, steady_state_wait_duration=steady_state_wait_duration, error_limit=error_limit, max_time=max_time, cooldown_time=cooldown_time)
            
            # Update the minimum output of the actuator and the minimum PV of the sensor
            self.actuator.set_minimum_output(self.actuator.scale_to_actual(output))
            self.sensor.set_minimum_measurable_temperature(self.sensor.scale_to_actual(steady_state_control_PV))
            self.minimum_output_rise_time = t_steady
            self.minimum_output_tuned = True

    def tune_maximum_output_and_PV(self, 
                                   start_at: float = 0.2, 
                                   step_size: float = 0.1, 
                                   steady_state_wait_duration: float = 5 ,
                                   error_limit: float = 0.032, 
                                   max_time: float = 40, 
                                   cooldown_time: float = 10, 
                                   max_total_time: float = 600, 
                                   safety_margin: float = 0.082) -> None:
        """
        Automatically finds the maximum output of the plant 
        where the PV reaches the maximum safety limit. The 
        maximum output will be set to the output where the 
        PV reaches the maximum safety limit.
        """
        #TODO: FIX THIS, estimator and safety margin combination did not work smh
        if not self.maximum_output_tuned:
            def monitor_time():
                start_time = time.time()
                while (time.time() - start_time < max_total_time) and not self.maximum_output_tuned:
                    time.sleep(1)
                self.stop()
                if not self.maximum_output_tuned:
                    raise TimeoutError("Maximum total time exceeded and maximum output is not tuned yet. Stopping the process.")

            monitor_thread = threading.Thread(target=monitor_time)
            monitor_thread.start()

            try:
                maximum_from_three_outputs = start_at + 2 * step_size
                if maximum_from_three_outputs > 1.0:
                    raise ValueError("The first three outputs will exceed 1.0. Try reducing the step_size or start_at.")
                outputs = []
                steady_state_control_PVs = []
                temperature_model_converged = False
                for output in np.arange(start_at, 1, step_size):
                    outputs.append(output)
                    _, steady_state_control_PV, __, ___, ____ = self.get_time_to_steady_state(output, steady_state_wait_duration=steady_state_wait_duration, error_limit=error_limit, max_time=max_time, cooldown_time=cooldown_time)
                    steady_state_control_PVs.append(steady_state_control_PV)
                    if len(outputs) > 2:
                        if abs(steady_state_control_PVs[-1] - predicted_next_steady_state_control_PV) < error_limit:
                            temperature_model_converged = True
                            self.control_PV_interpolator = interp1d(outputs, steady_state_control_PVs, kind="linear", fill_value="extrapolate")
                            break
                    if len(outputs) > 1:
                        self.control_PV_interpolator = interp1d(outputs, steady_state_control_PVs, kind="linear", fill_value="extrapolate")
                        next_output = output + step_size
                        predicted_next_steady_state_control_PV = self.control_PV_interpolator(next_output)
                        if predicted_next_steady_state_control_PV > self.PV_maximum_safety_limit:
                            break
                if not temperature_model_converged:
                    raise ValueError("Temperature model did not converge. Error limit is too small.")
                predicted_steady_state_control_PV_at_1 = self.control_PV_interpolator(1)
                if predicted_steady_state_control_PV_at_1 > self.PV_maximum_safety_limit:
                    new_step_size = 0.25
                    next_output = 0.5
                    predicted_steady_state_control_PV_at_1 = self.control_PV_interpolator(next_output)
                    # Perform binary search to find the maximum output where the PV reaches the maximum safety limit - safety_margin
                    while predicted_steady_state_control_PV_at_1 > self.PV_maximum_safety_limit - safety_margin + error_limit or \
                            predicted_steady_state_control_PV_at_1 < self.PV_maximum_safety_limit - safety_margin - error_limit:
                        if predicted_steady_state_control_PV_at_1 > self.PV_maximum_safety_limit - safety_margin + error_limit:
                            next_output = next_output - new_step_size
                        else:
                            next_output = next_output + new_step_size
                        new_step_size /= 2
                        predicted_steady_state_control_PV_at_1 = self.control_PV_interpolator(next_output)
                    self.actuator.set_maximum_output(self.actuator.scale_to_actual(next_output))
                output_unit=self.actuator.get_output_unit()
                print(f"Maximum output is tuned to {self.actuator.maximum_output} {output_unit}.")
                self.maximum_output_tuned = True
            except Exception as e:
                print(e)
                raise e
            finally:
                self.stop()
                monitor_thread.join()
            
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

    def get_minimum_output_rise_time(self) -> float:
        """
        Returns the rise time of the plant to reach the 
        minimum output.
        """
        return self.minimum_output_rise_time