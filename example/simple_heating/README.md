## Standard Operating Procedure (SOP) for Simple Heating
This SOP is an example for a more generalized SOP.
1. Make sure all devices are turned on and router detects every ethernet connection (blipping LED lights).
2. Set Robot IP address to static IP. Input the IP address according to furnace subnet.
3. Set PC IP address according to furnace subnet by changing ethernet network properties.
4. Check PC, Furnace, and Robot IP address. The IP addresses must be in the same subnet. For example, in a 192.168.111 subnet, PC (192.168.111.111), Furnace (192.168.111.222), and Robot (192.168.111.112).
5. Do ping tests for each devices from the PC to test connection. (open command prompt and do “ping 192.168.111.222” and “ping 192.168.111.112” in this case).
6. Make sure robot has been started (brakes are deactivated) and the control is in “remote mode” rather than “local mode” on the teaching pendant. We need to implement additional emergency stop procedure in “remote mode”.
7. Make sure furnace is in “level 2 programmer” mode.
8. Stand far enough from the robot and furnace. Be ready to press emergency stop on the teaching pendant during an emergency.
