from enum import Enum
from alab_control.alab_control._base_phenom_device import PhenomDevice
# from .._base_phenom_device import PhenomDevice
import abc
import PyPhenom as ppi
import matplotlib.pyplot as plt
import numpy as np

class SEMError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code

class InstrumentMode(Enum):
    OFF = "Off"
    OPERATIONAL = "Operational"
    STANDBY = "Standby"
    HIBERNATE = "Hibernate"
    INITIALIZING = "Initializing"
    CLOSING_DOWN = "ClosingDown"
    ERROR = "Error"

class OperationalMode(Enum):
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
    NAVCAM = "NavCam"
    SEM = "SEM"

class SEMDevice(PhenomDevice):
    """
    Class for controlling a Scanning Electron Microscope (SEM).
    """

    def get_instrument_mode(self):
        """
        Get the current instrument mode of the Phenom.

        Returns:
            str: The current instrument mode.
        """
        if self.is_connected:
            try:
                mode = self.phenom.GetInstrumentMode()
                print(f"Instrument mode: {mode}")
                return InstrumentMode(str(mode))
            except ImportError:
                print("Error getting instrument mode")
        else:
            print("Device is not connected.")

    def get_operational_mode(self):
        """
        Get the operational status of the Phenom.

        Returns:
            str: The current operational mode.
        """
        if self.is_connected:
            try:
                mode = self.phenom.GetOperationalMode()
                print(f"Operational mode: {mode}")
                return OperationalMode(str(mode))
            except ImportError:
                print("Error getting operational mode")
        else:
            print("Device is not connected.")

    def activate(self):
        """
        Activate the Phenom, transitioning it to operational mode.
        """
        if self.is_connected:
            print("Device is connected.")
            return self.phenom.Activate() # how do we know if it is activated  -> if operational mode is unavailable
        else:
            print("Device is not connected.")
    
    def load(self):
        """
        Load the sample. This calls the LiveNavCam
        """
        if self.is_connected:
            if self.get_instrument_mode() == "Operational":
                return self.phenom.Load()
            else:
                print("Device is not in operational mode, activate first.")
        else:
            print("Device is not connected.")
       
    
    def unload(self):
        """
        Unload the sample.
        """
        if  self.get_operational_mode() == "Loadpos":
            return self.phenom.Unload()
        else:
            print("Device is not in Loadpos operational mode.")
    
    def standby(self):
        """
        Set Phenom in standby mode.
        """
        return self.phenom.StandBy()
    
    def hibernate(self):
        """
        Set Phenom in hibernate mode.
        """
        return self.phenom.Hibernate()
    
    def poweroff(self):
        """
        Swich off Phenom.
        """
        return self.phenom.PowerOff()

    def toNav(self):
        """
        Switches the Phenom device to use the navigation camera.
        """
        if not self.is_connected:
            print("Device is not connected. Please connect the device first.")
            return

        try:
            self.phenom.MoveToNavCam()
            print("Successfully switched to navigation camera.")
        except ImportError:
            print("Failed to switch to navigation camera")

    def toSEM(self):
        """
        Switch to live SEM view.
        """
        if self.is_connected:
            try:
                self.phenom.MoveToSem()
                print("Successfully switched to SEM view.")
            except ImportError:
                print("Failed to switch to SEM view")
        else:
            print("Device is not connected.")
        # check that self.get_operational_mode() ==SelectingSem

    def AutoFocus(self):
        """
        Automatically optimize the focus.
        """
        if self.is_connected:
            try:
                self.phenom.SemAutoFocus()
                print("Auto-focus completed.")
            except ImportError:
                print("Auto-focus failed")
        else:
            print("Device is not connected.")

    def AutoContrastBrightness(self):
        """
        Automatically optimize contrast and brightness.
        """
        if self.is_connected:
            try:
                self.phenom.SemAutoContrastBrightness()
                print("Auto-contrast and brightness optimization completed.")
            except ImportError:
                print("Failed to optimize contrast and brightness")
        else:
            print("Device is not connected.")

    def adjust_focus(self, amt):
        """
        Adjust the focus based on a given amount.
        """
        if self.is_connected:
            try:
                current_wd = self.phenom.GetSemWD()
                new_wd = amt * current_wd
                self.phenom.SetSemWD(new_wd)
                print("Focus adjusted.")
            except ImportError:
                print("Failed to adjust focus")
        else:
            print("Device is not connected.")

    def moveto(self, x, y):
        """
        Move to a position specified by absolute coordinates.
        x, y: 
            Stage position in absolute coordinates (in millimeters)
        """
        if self.is_connected:
            try:
                self.phenom.MoveTo(x * 0.001, y * 0.001)
                print("Movement completed.")
            except ImportError:
                print("Failed to move")
        else:
            print("Device is not connected.")

    def moveby(self, delta_x, delta_y):
        """
        Move to a position specified relative to the current position
        delta_x: 
            Stage movement in x-direction, in meters from the current position.
        delta_y: 
            Stage movement in y-direction, in meters from the current position.
        """
        if self.is_connected:
            try:
                self.phenom.MoveBy(delta_x * 0.001, delta_y * 0.001)
                print("Movement completed.")
            except ImportError:
                print("Failed to move")
        else:
            print("Device is not connected.")

    def getsemhightension(self):
        """ 
        Get the SEM Hight Tension value. 
        """
        value = - self.phenom.GetSemHighTension()
        print(f"SEM high tension is: {value}")
        return value
       
    def setsemhightension(self, value):
        """ 
        Set the SEM Hight Tension value. 
        """
        print(f"Setting the SEM high tension to {value}")
        return self.phenom.SetSemHighTension(-value)

    def getsemspotsize(self):
        """
        Query the current SEM spot size (in Amps / Volt½)
        """
        value=self.phenom.GetSemSpotSize()
        return value
    
    def setsemspotsize(self,value):
        """
        Set the SEM spot size (in Amps / Volt½)
        TODO: default values and range
        For now should just use one fixed value (MAP) as spot size change might need stigmate calibration.
        """
        return self.phenom.SetSemSpotSize(value)
   
    def getframewidth(self):
        """
        Get the current frame width.
        """
        if self.is_connected:
            try:
                value=self.phenom.GetHFW()
                print(value)
                return value
            except ImportError:
                print("Failed to get frame width")
                return None
        else:
            print("Device is not connected.")
            return None

    def zoom(self, amt):
        """
        Zoom in or out by a given amount.
        """
        if self.is_connected:
            try:
                current_width = self.phenom.GetHFW()
                new_width = amt * current_width
                self.phenom.SetHFW(new_width)
                print("Zoom adjusted.")
            except ImportError:
                print("Failed to adjust zoom")
        else:
            print("Device is not connected.")

    def magnification(self, display_size=0.5):
        """
        Returns the image magnification for the given HFW relative to the given display size.
        """
        magnification =  self.phenom.MagnificationFromFieldWidth(self.phenom.GetHFW(), display_size)
        print(display_size)
        print(magnification)
        return magnification

    def save_image(self, fname='Image.tiff', res_x=1080, res_y=1080, frame_avg=16):
        """
        Save an SEM image.
        """
        if self.is_connected:
            try:
                acq = self.phenom.SemAcquireImage(res_x, res_y, frame_avg)
                self.phenom.Save(acq, fname)
                print(f"Image saved as {fname}.")
            except ImportError:
                print("Failed to save image")
        else:
            print("Device is not connected.")

    def get_image_data(self, res_x=1080, res_y=1080, frame_avg=16):
        """
        Get SEM image data.
        """
        if self.is_connected:
            try:
                acq = self.phenom.SemAcquireImage(res_x, res_y, frame_avg)
                img_data = np.asarray(acq.image)
                return img_data
            except ImportError:
                print("Failed to get image data")
                return None
        else:
            print("Device is not connected.")
            return None

    def show_image(self):
        """
        Display the SEM image.
        """
        img = self.getImageData()
        if img is not None:
            plt.imshow(img, cmap='gray')
            plt.show()
        else:
            print("No image data to display.")