from enum import Enum
import abc
import time
import matplotlib.pyplot as plt
import numpy as np
import sys
# from .._base_phenom_device import PhenomDevice

class SEMError(Exception):
    """ 
    Custom exception class for SEM-related errors.
    """
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code

class InstrumentMode(Enum):
    """ 
    Enumeration of possible operational states for an SEM instrument.

    Attributes:
        OFF (str): Indicates the instrument is turned off.
        OPERATIONAL (str): Indicates the instrument is operational and ready to use.
        STANDBY (str): Indicates the instrument is in standby mode.
        HIBERNATE (str): Indicates the instrument is in hibernate mode to save power.
        INITIALIZING (str): Indicates the instrument is initializing.
        CLOSING_DOWN (str): Indicates the instrument is in the process of shutting down.
        ERROR (str): Indicates the instrument is experiencing an error.
    """
    OFF = "Off"
    OPERATIONAL = "Operational"
    STANDBY = "Standby"
    HIBERNATE = "Hibernate"
    INITIALIZING = "Initializing"
    CLOSING_DOWN = "ClosingDown"
    ERROR = "Error"

class OperationalMode(Enum):
    """
    Enumeration of specific operational modes for managing SEM navigation and imaging functionalities.

    Attributes:
        UNAVAILABLE (str): Mode when operation is unavailable.
        LOAD_POS (str): Load position mode for loading samples.
        UNLOADING (str): Mode for unloading samples.
        SELECTING_NAVCAM (str): Mode for selecting the navigation camera.
        SELECTING_SEM (str): Mode for selecting the SEM for operations.
        LIVE_NAVCAM (str): Live feed mode for the navigation camera.
        LIVE_SEM (str): Live feed mode for the SEM.
        ACQUIRE_NAVCAM_IMAGE (str): Mode to acquire images from the navigation camera.
        ACQUIRE_SEM_IMAGE (str): Mode to acquire images using the SEM.
    """
    UNAVAILABLE = "Unavailable"
    LOAD_POS = "Loadpos"
    UNLOADING = "Unloading"
    SELECTING_NAVCAM = "SelectingNavCam"
    SELECTING_SEM = "SelectingSem"
    LIVE_NAVCAM = "LiveNavCam"
    LIVE_SEM = "LiveSem"
    ACQUIRE_NAVCAM_IMAGE = "AcquireNavCamImage"
    ACQUIRE_SEM_IMAGE = "AcquireSemImage"

    #when InstrumentMode = operational you could do load
    #stnad by means unavlualbel , activate means operational

# got graphic inter ->check if its is connected -> standby(means door is closed the machine is sleeping)
# -> initializing? -> operational -> picture with 32 sample -> load() and check if it is loadpos? does it mean lowading to sem
#->  move navcam to the desire sample number (by position x,y) check that the nav cam moved where we wanted it -> run sem-eds -> for all samples -> 
#  -> for every step check that it is done(blocks everything else) before moving to the next
class ImagingDevice(Enum):
    """
    Enumeration representing the types of imaging devices available in a system.

    Attributes:
        NAVCAM (str): Represents a Navigation Camera, used for general viewing and navigation purposes.
        SEM (str): Represents a Scanning Electron Microscope, used for high-resolution imaging at the microscale.
    """
    NAVCAM = "NavCam"
    SEM = "SEM"

class PhenomDriver():
    """
    Class for controlling a Scanning Electron Microscope (SEM).
    """
    def __init__(self, license_details):
        """
        Initialize the Phenom device with license installation.
        
        Args:
            device_name (str): A descriptive name for the Phenom device.
            license_details (dict): Details necessary for license installation, including 'instrument', 'username', 'password', and optionally 'PhenomID' if it's different from the instrument for licensing.
        """
        self.license_details = license_details
        self.phenom = None  # This will be initialized in the connect method
        self.is_connected = False
        self.phenomID = license_details.get('PhenomID', '')  # Optional: Use a specific PhenomID if provided
        self.have_just_move_to_SEM = True

    def install_license(self):
        """
        Install and verify the license for the Phenom device.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi
        # Extracting license details
        instrument = self.license_details.get('instrument')
        username = self.license_details.get('username')
        password = self.license_details.get('password')

        # Install the license
        ppi.InstallLicense(instrument, username, password)

        # Optionally, verify the license installation
        for license in ppi.GetLicenses():
            print('Phenom-ID:', license.instrumentId)
            print('Username:', license.username)
            print('Password:', license.password)

    def connect(self):
        """
        Connect to the Phenom device.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi

        try:
            if self.phenomID:
                self.phenom = ppi.Phenom(self.phenomID, self.license_details['username'], self.license_details['password'])
            else:
                self.phenom = ppi.Phenom()
            self.is_connected = True
            print("Phenom connected successfully.")
            return True
        except ImportError:
            print("Failed to connect to Phenom.")
            self.is_connected = False
            return False

    def disconnect(self):
        """
        Disconnect from the Phenom device.
        """
        self.is_connected = False
        print("Phenom disconnected.")
        return True
    
    def reset_have_just_move_to_SEM(self):
        self.have_just_move_to_SEM = True

    def get_instrument_mode(self) -> str:
        """
        Get the current instrument mode of the Phenom.

        Returns:
            str: The current instrument mode.
        """
        if self.is_connected:
            try:
                mode = self.phenom.GetInstrumentMode()
                print(f"Instrument mode: {mode}")
                return True, str(mode)
            except ImportError:
                print("Error getting instrument mode")
                return False, None
        else:
            print("Device is not connected.")
            return False, None

    def get_operational_mode(self) -> str:
        """
        Get the operational status of the Phenom.

        Returns:
            str: The current operational mode.
        """
        if self.is_connected:
            try:
                mode = self.phenom.GetOperationalMode()
                print(f"Operational mode: {mode}")
                return True, str(mode)
            except ImportError:
                print("Error getting operational mode")
                return False, None
        else:
            print("Device is not connected.")
            return False, None

    def activate(self):
        """
        Activate the Phenom, transitioning it to operational mode.
        """
        if self.is_connected:
            print("Device is connected.")
            self.phenom.Activate()
            return True
        else:
            print("Device is not connected.")
            return False
    
    def load(self):
        """
        Load the sample. 
        This has to be done when OperationalMode is LoadPos and InstrumentMode is Operational.
        This changes the OperationalMode to LiveNavCam.
        """
        if self.is_connected:
            print(str(self.get_instrument_mode()))
            if self.get_instrument_mode() == InstrumentMode("Operational") and self.get_operational_mode() == OperationalMode("Loadpos"): #"Operational"
                self.phenom.Load()
                return True
            else:
                print("Instrument mode is not in Operational and operational mode is not in Loadpos, activate first.")
                return False
        else:
            print("Device is not connected.")
            return False

    def unload(self):
        """
        Unload the sample. Only unloads the sample and not open door TODO: FIND OPEN DOOR.
        """
        if self.is_connected:
            if self.get_instrument_mode() == InstrumentMode("Operational") and self.get_operational_mode() == OperationalMode("LiveNavCam"): 
                self.phenom.Unload()
                return True
            else:
                print("Device is not in Loadpos operational mode.")
                return False
        else:
            print("Device is not connected.")
            return False
    
    def standby(self):
        """
        Set Phenom in standby mode.
        """
        if self.is_connected:
            self.phenom.Standby()
            return True
        else:
            print("Device is not connected.")
            return False
    
    # def hibernate(self):
    #     """
    #     Set Phenom in hibernate mode.
    #     CAUTION: UNTESTED.
    #     """
    #     return self.phenom.Hibernate()
    
    # def poweroff(self):
    #     """
    #     Switch off Phenom. 
    #     WARNING!!!: WE DO NOT TEST THIS AS THIS WILL SHUTDOWN THE PHENOM FOR 14 HOURS OR MORE AND REQUIRE A LOT OF MANUAL HANDLING BEFOREHAND
    #     """
    #     return self.phenom.PowerOff()

    def to_nav(self):
        """
        Switches the Phenom device to use the navigation camera.
        """
        if not self.is_connected:
            print("Device is not connected. Please connect the device first.")
            return False
        try:
            self.phenom.MoveToNavCam()
            print("Successfully switched to navigation camera.")
            return True
        except ImportError:
            print("Failed to switch to navigation camera")
            return False

    def to_SEM(self, max_retries=2):
        """
        Switch to live SEM view.
        max_retries:
            Maximum number of retries to switch to SEM view (default is 2)
        """
        if self.is_connected:
            wait_time = 30
            retries = 0
            while retries < max_retries:
                try:
                    self.phenom.MoveToSem()
                    print("Successfully switched to SEM view.")
                    return True
                except:
                    retries += 1
                    print(f'Failed to switch to SEM view. Attempt {retries} of {max_retries}.\nWaiting {wait_time} seconds before retrying.')
                    time.sleep(wait_time)
            print("Maximum retries reached. Failed to switch to SEM view.")
            return False
        else:
            print("Device is not connected.")
            return False

    def auto_focus(self):
        """
        Automatically optimize the focus.
        """
        if self.is_connected:
            try:
                self.phenom.SemAutoFocus()
                print("Auto-focus completed.")
                return True
            except ImportError:
                print("Auto-focus failed")
                return False
        else:
            print("Device is not connected.")
            return False

    def auto_contrast_brightness(self):
        """
        Automatically optimize contrast and brightness.
        """
        if self.is_connected:
            try:
                self.phenom.SemAutoContrastBrightness()
                print("Auto-contrast and brightness optimization completed.")
                return True
            except ImportError:
                print("Failed to optimize contrast and brightness")
                return False
        else:
            print("Device is not connected.")
            return False

    def adjust_focus(self, new_wd):
        """
        Adjust the focus into some working distance in mm.
        """
        if self.is_connected:
            try:
                self.phenom.SetSemWD(new_wd * 0.001)
                print("Focus adjusted.")
                return True
            except ImportError:
                print("Failed to adjust focus")
                return False
        else:
            print("Device is not connected.")
            return False

    def move_to(self, x, y):
        """
        Move to a position specified by absolute coordinates.
        x, y: 
            Stage position in absolute coordinates (in millimeters)
        """
        if self.is_connected:
            try:
                self.phenom.MoveTo(x * 0.001, y * 0.001)
                print("Movement completed.")
                return True
            except ImportError:
                print("Failed to move")
                return False
        else:
            print("Device is not connected.")
            return False

    def move_by(self, delta_x, delta_y):
        """
        Move to a position specified relative to the current position
        delta_x: 
            Stage movement in x-direction, in milimeters from the current position.
        delta_y: 
            Stage movement in y-direction, in milimeters from the current position.
        """
        if self.is_connected:
            try:
                self.phenom.MoveBy(delta_x * 0.001, delta_y * 0.001)
                print("Movement completed.")
                return True
            except ImportError:
                print("Failed to move")
                return False
        else:
            print("Device is not connected.")
            return False

    #TODO: CHK DTYPE
    def position(self):
        """
        Get the current position of the stage.
        """
        if self.is_connected:
            try:
                pos = self.phenom.GetCurrentPos()
                print(f"Current position: {pos}")
                return True, (float(position) for position in pos)
            except ImportError:
                print("Failed to get position")
                return False, None
        else:
            print("Device is not connected.")
            return False, None

    def get_sem_high_tension(self):
        """ 
        Get the SEM High Tension value (in Volt). 
        """
        if self.is_connected:
            value = - self.phenom.GetSemHighTension()
            print(f"SEM high tension is: {value} Volts.")
            return True, float(value)
        else:
            print("Device is not connected.")
            return False, None
       
    def set_sem_high_tension(self, value):
        """ 
        Set the SEM High Tension value (in Volt). 
        """
        if self.is_connected:
            self.phenom.SetSemHighTension(-value)
            print(f"Setting the SEM high tension to {value} Volts.")
            return True
        else:
            print("Device is not connected.")
            return False

    def get_sem_spot_size(self):
        """
        Query the current SEM spot size (in Amps / Volt½)
        """
        if self.is_connected:
            value=self.phenom.GetSemSpotSize()
            print(f"SEM Beam intensity (spot size) is: {value} Amps / Volt½")
            return True, float(value)
        else:
            print("Device is not connected.")
            return False, None
    
    def set_sem_spot_size(self,value):
        """
        Set the SEM spot size (in Amps / Volt½)
        Range is between 2.1 and 5.1 Amps / Volt½. Raise error if value is out of range.
        For now should just use one fixed value (MAP) as spot size change might need stigmate calibration.
        """
        if self.is_connected:
            if value < 2.1 or value > 5.1:
                print("SEM Beam intensity (spot size) value out of range. Please use a value between 2.1 and 5.1 Amps / Volt½.")
                return False
            self.phenom.SetSemSpotSize(value)
            value_get=self.phenom.GetSemSpotSize()
            print(f"SEM Beam intensity (spot size) set to {value_get} Amps / Volt½")
            return True
        else:
            print("Device is not connected.")
            return False
   
    def get_frame_width(self):
        """
        Get the current frame width.
        """
        if self.is_connected:
            try:
                value=self.phenom.GetHFW()
                print(f"Frame width (FW) is: {value} mm.")
                return True, float(value)
            except ImportError:
                print("Failed to get frame width")
                return False, None
        else:
            print("Device is not connected.")
            return False, None

    def zoom(self, amt):
        """
        Zoom in or out by a given amount. 0.5 is 50% zoom in, 2 is 200% zoom out.
        """
        if self.is_connected:
            try:
                current_width = self.phenom.GetHFW()
                new_width = amt * current_width
                self.phenom.SetHFW(new_width)
                print("Zoom adjusted.")
                return True
            except ImportError:
                print("Failed to adjust zoom")
                return False
        else:
            print("Device is not connected.")
            return False

    def get_magnification(self):
        """
        Returns the image magnification shown in the phenom GUI.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi
        if self.is_connected:
            magnification = ppi.MagnificationFromFieldWidth(self.phenom.GetHFW())
            return True, float(magnification)
        else:
            print("Device is not connected.")
            return False, None
    
    def framewidth(self):
        """Returns the frame width."""
        if self.is_connected:
            current_width = self.phenom.GetHFW()
            return True, current_width
        else:
            print("Device is not connected.")
            return False, None

    def save_image(self, fname='Image.tiff', res_x=1080, res_y=1080, frame_avg=16):
        """
        Save an SEM image.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi
        if self.is_connected:
            try:
                acq = self.phenom.SemAcquireImage(res_x, res_y, frame_avg)
                ppi.Save(acq, fname)
                print(f"Image saved as {fname}.")
                return True
            except ImportError:
                print("Failed to save image")
                return False
        else:
            print("Device is not connected.")
            return False

    def get_image_data(self, res_x=1080, res_y=1080, frame_avg=16):
        """
        Get SEM image data.
        """
        if self.is_connected:
            try:
                acq = self.phenom.SemAcquireImage(res_x, res_y, frame_avg)
                if type(acq) == np.ndarray:
                    acq = acq.tolist()
                return True, acq
            except ImportError:
                print("Failed to get image data")
                return False, None
        else:
            print("Device is not connected.")
            return False, None

    # def get_image_info(self, file_path):
    #     """
    #     Get SEM image info (metadata).
    #     """
    #     if self.is_connected:
    #         try:
    #             acq = self.phenom.GetImageInfo(file_path)
    #             return acq
    #         except ImportError:
    #             print("Failed to get image info")
    #             return None
    #     else:
    #         print("Device is not connected.")
    #         return None

    # def show_image(self):
    #     """
    #     Display the SEM image.
    #     """
    #     img = self.get_image_data()
    #     img = np.asarray(img[0])
    #     if img is not None:
    #         plt.imshow(img, cmap='gray')
    #         plt.show()
    #     else:
    #         print("No image data to display.")

    def get_pressure(self):
        """
        Get the current vacuum pressure in the SEM chamber.
        """
        if self.is_connected:
            pressure = self.phenom.SemGetVacuumChargeReductionState().pressureEstimate
            print(f"Current vacuum pressure: {pressure} Pa.")
            return True, float(pressure)
        else:
            print("Device is not connected.")
            return False, None

    # def load_pulse_processor_settings(self):
    #     """
    #     Load pulse processor settings.
    #     """
    #     if self.is_connected:
    #         try:
    #             self.phenom.LoadPulseProcessorSettings()
    #             print("Pulse processor settings loaded successfully.")
    #             return True
    #         except ImportError:
    #             print("Failed to load pulse processor settings.")
    #             return False
    #     else:
    #         print("Device is not connected.")
    #         return False
    
    # def get_spectroscopy_element(self, element_name):
    #     """
    #     Returns the spectroscopy element information for the given element name.
    #     """
    #     if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
    #         import PyPhenom as ppi
    #     if self.is_connected:
    #         try:
    #             element = ppi.Spectroscopy.Element(element_name)
    #             return True, str(element)
    #         except ImportError:
    #             print(f"Failed to get spectroscopy element information for {element_name}.")
    #             return False, None
    #     else:
    #         print("Device is not connected.")
    #         return False, None
        
    # def get_position(self, x, y):
    #     """
    #     Gets the position using the specified x and y relative coordinates.
    #     """
    #     if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
    #         import PyPhenom as ppi
        
    #     try:
    #         position = ppi.Position(x, y)
    #         return position
    #     except ImportError:
    #         print(f"Failed to set position to ({x}, {y}).")
    #         return None
        
    def run_eds_job_analyzer(self):
        """
        Runs the EDS Job Analyzer on the Phenom device.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi
        
        try:
            analyzer = ppi.Application.ElementIdentification.EdsJobAnalyzer(self.phenom)
            print("EDS Job Analyzer initialized successfully.")
            return analyzer
        except ImportError:
            print("Failed to initialize EDS Job Analyzer.")
            return None

    def quantify_spectrum(self, spectrum, elements):
        """
        Quantifies the given spectrum for the specified elements.
        
        Parameters:
        - spectrum: The spectrum to be quantified.
        - elements: A list of elements to quantify in the spectrum.
        
        Returns:
        - The quantified result if successful, None otherwise.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi
        
        try:
            quantified_result = ppi.Spectroscopy.Quantify(spectrum, elements)
            print("Spectrum quantified successfully.")
            return quantified_result
        except ImportError:
            print("Failed to quantify spectrum.")
            return None
        
    def write_msa_file(self, msa_data, filename):
        """
        Writes the given EDS acquisition or MSA data to a specified file.

        Parameters:
        - msa_data: The MSA data or EDS acquisition data to be written.
        - filename: The name of the file to write the data to.

        Returns:
        - True if the file was written successfully, False otherwise.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi
        
        try:
            ppi.Spectroscopy.WriteMsaFile(msa_data, filename)
            print(f"Data written successfully to {filename}.")
            return True
        except ImportError:
            print("Failed to import necessary modules for writing MSA file.")
            return False
        except Exception as e:
            print(f"An error occurred while writing the MSA file: {e}")
            return False
    
    def set_detector(self, detector_name):
        """
        Set the detector to use.

        Args:
            detector_name (str): Name of the detector to use. Can be one of the following:
                "BSD All", "BSD NorthSouth", "BSD EastWest", "SED", "BSD A", "BSD B", "BSD C", "BSD D"
        
        Returns:
            detector_name (str): Name of the detector set.
        """
        if "ppi" not in list(sys.modules.keys()) or "PyPhenom" not in list(sys.modules.keys()):
            import PyPhenom as ppi
        if detector_name == "BSD All":
            requested_mode = ppi.DetectorMode.All
        elif detector_name == "BSD NorthSouth":
            requested_mode = ppi.DetectorMode.NorthSouth
        elif detector_name == "BSD EastWest":
            requested_mode = ppi.DetectorMode.EastWest
        elif detector_name == "SED":
            if self.get_pressure() > 1:
                # wait for 2 minute max for the pressure to drop below 1 Pa and check again every 10 seconds
                for i in range(12):
                    if self.get_pressure() <= 1:
                        break
                    time.sleep(10)
                if self.get_pressure() > 1:
                    raise SEMError("Cannot enable SED when vacuum pressure is above 1 Pa.")
            try:
                if self.have_just_move_to_SEM:
                    self.phenom.SemEnableSed()
                    self.have_just_move_to_SEM = False
                    time.sleep(60)
                else:
                    self.phenom.SemEnableSed()
                requested_mode = ppi.DetectorMode.Sed
            except ppi.Error as e:
                raise SEMError(f"Failed to enable SED detector. Error message: {e.args[0]}.")
        elif detector_name == "BSD A":
            requested_mode = ppi.DetectorMode.A
        elif detector_name == "BSD B":
            requested_mode = ppi.DetectorMode.B
        elif detector_name == "BSD C":
            requested_mode = ppi.DetectorMode.C
        elif detector_name == "BSD D":
            requested_mode = ppi.DetectorMode.D
        else:
            raise SEMError("Invalid viewing mode specified.")
        viewingMode = self.phenom.GetSemViewingMode()
        viewingMode.scanParams.detector = requested_mode
        self.phenom.SetSemViewingMode(viewingMode)
        return detector_name
