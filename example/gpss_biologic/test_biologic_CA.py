import logging

logging.basicConfig(level=logging.DEBUG)

import easy_biologic as ebl
import easy_biologic.base_programs as blp        
from easy_biologic.lib.ec_lib import IRange
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

save_path_peis = 'ca.csv'


bl = ebl.BiologicDevice('192.168.1.33')

params_ca = {
    'voltages': [0.1],
    'durations': [3600],
    "time_interval": 1,
    "current_interval": 0.001,
    "current_range": IRange.AUTO
}

peis = blp.CA(
    bl,
    params_ca,
    channels=[0]
)

peis.run(True)
peis.save_data(save_path_peis)
