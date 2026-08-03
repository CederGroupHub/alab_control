import logging

logging.basicConfig(level=logging.DEBUG)

import easy_biologic as ebl
import easy_biologic.base_programs as blp        
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
# # Run PEIS
save_path_peis = 'peis.csv'


bl = ebl.BiologicDevice('192.168.1.33')
# bl.connect()
# print(bl.techniques)
# # print(bl.channel_configuration(0))
# exit()

"""
Params
voltage: Initial potential in Volts.

amplitude_voltage: Sinus amplitude in Volts.

initial_frequency: Initial frequency in Hertz.

final_frequency: Final frequency in Hertz.

frequency_number: Number of frequencies.

duration: Overall duration in seconds.

vs_initial: If step is vs. initial or previous. [Default: False]

time_interval: Maximum time interval between points in seconds. [Default: 1]

current_interval: Maximum time interval between points in Amps. [Default: 0.001]

sweep: Defines whether the spacing between frequencies is logarithmic ('log') or linear ('lin'). [Default: 'log']

repeat: Number of times to repeat the measurement and average the values for each frequency. [Default: 1]

correction: Drift correction. [Default: False]

wait: Adds a delay before the measurement at each frequency. The delay is expressed as a fraction of the period. [Default: 0]"""
params_peis = {
    'voltage': 0,
    'final_frequency': 1e2,
    'initial_frequency': 1e6,
    'amplitude_voltage': 0.01,
    'frequency_number': 60,
    'duration': 0.,
    'repeat': 2,
    'wait': 0.10
}

peis = blp.PEIS(
    bl,
    params_peis,
    channels=[0]
)

peis.run(True)
peis.save_data(save_path_peis)


# Plot Nyquist plot

# Read PEIS data
data = pd.read_csv(save_path_peis, skiprows=1)
# Calculate real and imaginary components
data["ReIm"] = data["Impedance modulus"] * np.cos(data["Impedance phase"])
data["ImRe"] = -data["Impedance modulus"] * np.sin(data["Impedance phase"])

# Create Nyquist plot
plt.figure(figsize=(8, 8))
plt.plot(data["ReIm"], data["ImRe"], 'bo-')
plt.xlabel("Z' (Ω)")
plt.ylabel("-Z'' (Ω)")
plt.title("Nyquist Plot")
plt.grid(True)
plt.axis('equal')  # Equal aspect ratio
plt.show()
