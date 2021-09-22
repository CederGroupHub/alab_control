# furnace_epc_3016

This package is used to control Furnace's process controller via Modbus protocol

## Usage

```python
from datetime import timedelta

from alab_control.furnace_epc_3016 import (
    FurnaceController, 
    SegmentType, 
    SegmentArgs
)

furnace = FurnaceController("192.168.111.222")

# configure the segment
program = [
    SegmentArgs(SegmentType.RAMP_TIME, target_setpoint=50,
                time_to_target=timedelta(hours=1)),
    SegmentArgs(SegmentType.DWELL, duration=timedelta(hours=5)),
    SegmentArgs(SegmentType.STEP, target_setpoint=0)
]

# run the program
furnace.run_program(*program)

# check if it is running (safe to open)
furnace.is_running()

# stop program
furnace.stop()
```