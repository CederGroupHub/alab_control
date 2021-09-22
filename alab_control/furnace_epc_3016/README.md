# furnace_epc_3016

This package is used to control Furnace's process controller via Modbus protocol

## Usage

```python
from datetime import timedelta

from alab_control.furnace_epc_3016 import (
    FurnaceController,
    SegmentType,
    Segment
)

furnace = FurnaceController("192.168.111.222")

# configure the segment
segments = [
    Segment(SegmentType.RAMP_TIME, target_setpoint=50,
            time_to_target=timedelta(hours=1)),
    Segment(SegmentType.DWELL, duration=timedelta(hours=5)),
    Segment(SegmentType.STEP, target_setpoint=0)
]

# run the program
furnace.run_program(*segments)

# check if it is running (safe to open)
furnace.is_running()

# read current temperature / current target temperature
furnace.current_temperature
furnace.current_target_temperature

# stop program
furnace.stop()
```