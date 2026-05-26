# Connecting to xarm on Mac
1. Set up the subnet mask to be the same as the robot controlled IP using: `sudo ifconfig en11 inet 192.168.1.10 netmask 255.255.255.0`and PIV authenticate it
2. set the port config `sudo ipconfig set en11 DHCP` (optional)
3. You can then check the connection through `ping 192.168.1.201`
4. Using UFactory app, you check connection and make sure the mode is set to "real robot"
5. en11 is an example on Mac and it would be different based on the connected port and the OS.
