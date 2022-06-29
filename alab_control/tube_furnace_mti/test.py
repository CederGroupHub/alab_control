import win32com.client  # Python ActiveX Client
import threading
import time
Input1 = 100  # First Number to Add
Input2 = 200  # Second Number to Add
LabVIEW = win32com.client.Dispatch("AutomaticLoadingFurnace2.Application")
VI = LabVIEW.getvireference(r'C:\Users\Yuxing Fei\projects\OTF-1200X-ASD\builds\2\Automatic loading furnace_2.'
                            r'exe\Automatic loading tube furnace_2.vi')  # Path to LabVIEW VI

VI.setcontrolvalue('Sample change completed', True)  # Set Input 1
# time.sleep(1)

# result = VI.getcontrolvalue('RUN_T')  # Get return value
