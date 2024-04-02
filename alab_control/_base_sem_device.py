import matplotlib.pyplot as plt
import PyPhenom as ppi
import numpy as np

class PhenomDevice():
    def __init__(self, device_name, connection_params, license_details):
        """
        Initialize the Phenom device with license installation.
        
        Args:
            device_name (str): A descriptive name for the Phenom device.
            connection_params (dict): Parameters necessary for establishing a connection to the device.
            license_details (dict): Details necessary for license installation, including 'instrument', 'username', and 'password'.
        """
        super().__init__(device_name, connection_params)
        self.license_details = license_details
        self.install_license()
        self.phenom = None  # Placeholder for the actual Phenom library device object, to be initialized in connect method
        self.is_connected = False

    def install_license(self):
        """
        Install and verify the license for the Phenom device.
        """
       
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
        Establish a connection to the Phenom device. Overrides the base class method.
        """

        try:
            self.phenom = ppi.Phenom()  # Initialize the actual Phenom device object
            self.is_connected = True
            print(f"{self.device_name} connected successfully.")
        except Exception as e:
            print(f"Failed to connect to {self.device_name}: {e}")
            self.is_connected = False

    def disconnect(self):
        """
        Disconnect from the Phenom device. Overrides the base class method.
        """
        self.is_connected = False
        print(f"{self.device_name} disconnected.")

    def send_request(self, endpoint, data=None, method="GET"):
        """
        Send a request to the Phenom device. Specific implementation of the base class's method.
        
        Args:
            endpoint (str): The endpoint or command to send to the device.
            data (dict, optional): Additional data or parameters for the request.
            method (str): The HTTP method (e.g., "GET", "POST") - applicable if interacting with a web service.
        
        This is a placeholder to demonstrate how you might structure a request to the Phenom device.
        Actual implementation will depend on the commands supported by the Phenom API.
        """
        # Implement how to send requests to the Phenom device using the PyPhenom library
        pass  #TODO
    
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
        except Exception as e:
            print(f"Failed to switch to navigation camera: {e}")

    def toSEM(self):
        """
        Switch to live SEM view.
        """
        if self.is_connected:
            try:
                self.phenom.MoveToSem()
                print("Successfully switched to SEM view.")
            except Exception as e:
                print(f"Failed to switch to SEM view: {e}")
        else:
            print("Device is not connected.")

    def AutoFocus(self):
        """
        Automatically optimize the focus.
        """
        if self.is_connected:
            try:
                self.phenom.SemAutoFocus()
                print("Auto-focus completed.")
            except Exception as e:
                print(f"Auto-focus failed: {e}")
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
            except Exception as e:
                print(f"Failed to optimize contrast and brightness: {e}")
        else:
            print("Device is not connected.")

    def adjustFocus(self, amt):
        """
        Adjust the focus based on a given amount.
        """
        if self.is_connected:
            try:
                current_wd = self.phenom.GetSemWD()
                new_wd = amt * current_wd
                self.phenom.SetSemWD(new_wd)
                print("Focus adjusted.")
            except Exception as e:
                print(f"Failed to adjust focus: {e}")
        else:
            print("Device is not connected.")

    def move(self, x, y):
        """
        Move to a relative position.
        """
        if self.is_connected:
            try:
                self.phenom.MoveBy(x, y)
                print("Movement completed.")
            except Exception as e:
                print(f"Failed to move: {e}")
        else:
            print("Device is not connected.")

    def framewidth(self):
        """
        Get the current frame width.
        """
        if self.is_connected:
            try:
                return self.phenom.GetHFW()
            except Exception as e:
                print(f"Failed to get frame width: {e}")
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
            except Exception as e:
                print(f"Failed to adjust zoom: {e}")
        else:
            print("Device is not connected.")

    def saveImage(self, fname='Image.tiff', res_x=1080, res_y=1080, frame_avg=16):
        """
        Save an SEM image.
        """
        if self.is_connected:
            try:
                acq = self.phenom.SemAcquireImage(res_x, res_y, frame_avg)
                ppi.Save(acq, fname)
                print(f"Image saved as {fname}.")
            except Exception as e:
                print(f"Failed to save image: {e}")
        else:
            print("Device is not connected.")

    def getImageData(self, res_x=1080, res_y=1080, frame_avg=16):
        """
        Get SEM image data.
        """
        if self.is_connected:
            try:
                acq = self.phenom.SemAcquireImage(res_x, res_y, frame_avg)
                img_data = np.asarray(acq.image)
                return img_data
            except Exception as e:
                print(f"Failed to get image data: {e}")
                return None
        else:
            print("Device is not connected.")
            return None

    def showImage(self):
        """
        Display the SEM image.
        """
        img = self.getImageData()
        if img is not None:
            plt.imshow(img, cmap='gray')
            plt.show()
        else:
            print("No image data to display.")



license_details = {
    'instrument': 'MVE081392-10796-L',
    'username': 'MVE08139210796L-1C',
    'password': 'WTE3TJW6B90Q',

}
phenom_device = PhenomDevice("Phenom ProX", {}, license_details)
phenom_device.connect()
