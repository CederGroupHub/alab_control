import PyPhenom as ppi

class PhenomDevice:
    def __init__(self, device_name, license_details):
        """
        Initialize the Phenom device with license installation.
        
        Args:
            device_name (str): A descriptive name for the Phenom device.
            license_details (dict): Details necessary for license installation, including 'instrument', 'username', 'password', and optionally 'PhenomID' if it's different from the instrument for licensing.
        """
        self.device_name = device_name
        self.license_details = license_details
        self.phenom = None  # This will be initialized in the connect method
        self.is_connected = False
        self.phenomID = license_details.get('PhenomID', '')  # Optional: Use a specific PhenomID if provided

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
        Connect to the Phenom device.
        """
        try:
            if self.phenomID:
                self.phenom = ppi.Phenom(self.phenomID, self.license_details['username'], self.license_details['password'])
            else:
                self.phenom = ppi.Phenom()
            self.is_connected = True
            print(f"{self.device_name} connected successfully.")
        except ImportError:
            print(f"Failed to connect to {self.device_name}")
            self.is_connected = False

    def disconnect(self):
        """
        Disconnect from the Phenom device.
        """
        self.is_connected = False
        print(f"{self.device_name} disconnected.")


# license_details = {
#     'instrument': 'MVE081392-10796-L',
#     'username': 'MVE08139210796L-1C',
#     'password': 'WTE3TJW6B90Q',

# }
# phenom_device = PhenomDevice("Phenom ProX", {}, license_details)
# phenom_device.connect()
