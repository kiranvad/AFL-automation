# Connecting to xarm
1. While connecting to xarm through LAN, initially the port connection is refused until either you specify the connection to be on the same subnet mask or use `sudo ipconfig set en11 DHCP` and PIV authenticate it.
2. You can then check the connection through `ping 192.168.1.201`
3. This is affter you set up the subnet mask to be the same as the robot controlled IP using: `sudo ifconfig en11 inet 192.168.1.10 netmask 255.255.255.0`