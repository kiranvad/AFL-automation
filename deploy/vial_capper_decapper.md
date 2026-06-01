# Vial Capper and Decapper Setup Guide for AFL-automation

This guide explains how to set up a Raspberry Pi based vial capper and decapper so that it can be controlled through the AFL-automation API over Ethernet.

The goal is to make the setup process understandable even if you are new to Raspberry Pi, motors, or APIs. The guide is written in a step-by-step way and tries to explain not only what to do, but also why you are doing it.

This document focuses on:
- the hardware connections
- preparing the Raspberry Pi
- installing the software environment
- understanding how AFL-automation exposes an API
- starting the API server on the Raspberry Pi
- connecting to the Raspberry Pi from another computer using its IP address
- testing the API safely

This document does not include the Python Driver implementation itself. The Driver is the piece of code that tells AFL-automation how to move your specific hardware. That code should live in the AFL-automation Python package, but it is intentionally not included here.

## 1. What this instrument does

This vial capper and decapper has two separate motions:

1. Vertical motion
   The stepper motor turns a lead screw. That lead screw moves the gripper assembly up and down.

2. Gripper motion
   A servo motor opens and closes a two-finger gripper.

In other words:
- the stepper motor changes height
- the servo motor changes grip

This means the instrument can:
- move down toward a vial
- close the gripper around a cap or vial feature
- move up away from the vial
- open the gripper to release

If your mechanical design also includes a separate rotating mechanism for actually screwing and unscrewing threaded caps, that rotation would need to be controlled too. Based on the hardware description in this guide, the two motions currently described are vertical travel and gripper opening/closing.

## 2. How the control system is organized

The control system has four main parts:

1. Raspberry Pi
   This is the small computer that runs the AFL-automation API server.

2. DRV8824 or DRV8825 style stepper driver
   This board receives simple digital signals from the Raspberry Pi and uses them to drive the stepper motor.

3. PCA9685 servo driver
   This board communicates with the Raspberry Pi over I2C and generates the servo control signal.

4. Control computer
   This is your laptop or desktop computer. It sends HTTP requests over Ethernet to the Raspberry Pi by using the Pi's IP address.

The important idea is this:

The Raspberry Pi is the machine that directly controls the motors.
The control computer does not directly toggle GPIO pins.
The control computer only talks to the Raspberry Pi through the AFL-automation API.

## 3. High-level software flow

The software flow looks like this:

1. You power on the Raspberry Pi.
2. The Raspberry Pi runs an AFL-automation API server.
3. That API server loads a hardware-specific Driver.
4. The Driver knows how to move the stepper motor and servo motor.
5. Another computer sends commands to the Pi using the Pi's IP address.
6. The Pi receives the command and tells the hardware what to do.

For example:
- your computer sends a request like "move down 10 mm"
- the Raspberry Pi receives that request
- the Driver converts that request into step pulses for the DRV8824
- the stepper motor moves the gripper downward

## 4. Hardware overview

Your hardware arrangement is:

- Raspberry Pi
- stepper motor connected through a DRV8824 driver
- lead screw attached to the stepper motor
- two-finger gripper mounted on the moving stage
- servo motor attached to the gripper
- PCA9685 connected to the Raspberry Pi for servo control
- Ethernet connection from the Raspberry Pi to the control computer or local network

## 5. Important safety notes before wiring

Before connecting anything, read these carefully.

1. Do not power the stepper motor directly from the Raspberry Pi.
   The Raspberry Pi cannot supply enough current for a stepper motor.

2. Do not power the servo directly from the Raspberry Pi 5V pin unless you are absolutely sure the current draw is small enough.
   Many servos draw enough current to cause brownouts or unstable behavior.

3. Use a proper external power supply for the stepper motor.
   The DRV8824 motor supply should come from a separate motor power source that matches the motor requirements.

4. Use a proper external power supply for the servo rail on the PCA9685.
   The PCA9685 logic side talks to the Pi, but the servo power should usually come from a separate 5V to 6V supply.

5. Make sure all grounds are shared.
   The Raspberry Pi ground, DRV8824 ground, PCA9685 ground, and external power supply grounds must be connected together so that all control signals have the same reference.

6. Never connect or disconnect motor wires while power is on.
   This can damage the driver.

7. Start with low speeds and short travel distances.
   This reduces the chance of crashing the mechanism.

## 6. Suggested wiring plan

### 6.1 Raspberry Pi to PCA9685

The PCA9685 uses I2C communication.

Typical connections are:
- Pi GPIO2 SDA to PCA9685 SDA
- Pi GPIO3 SCL to PCA9685 SCL
- Pi 3.3V to PCA9685 VCC or logic power input
- Pi GND to PCA9685 GND

Important note:
The PCA9685 logic side should use the correct logic voltage expected by the board. For most common breakout boards used with Raspberry Pi, the logic side is connected to 3.3V.

### 6.2 Servo power

Typical connections are:
- external 5V to 6V supply positive to PCA9685 V+ rail
- external supply ground to PCA9685 ground
- servo plugged into one PCA9685 channel

The servo signal comes from the PCA9685 channel.
The servo power should come from the external supply, not from the Pi.

### 6.3 Raspberry Pi to DRV8824

The DRV8824 style driver usually needs these control signals:
- STEP
- DIR
- ENABLE

A common example mapping is:
- Pi GPIO20 to STEP
- Pi GPIO21 to DIR
- Pi GPIO16 to ENABLE
- Pi GND to DRV8824 GND

The DRV8824 also needs:
- motor power supply connected to VMOT and GND
- stepper motor coils connected to the motor outputs

You must also set the current limit on the DRV8824 correctly for your motor. If you do not, the motor or driver can overheat.

### 6.4 Shared ground

This is extremely important.

The following grounds should all be connected together:
- Raspberry Pi ground
- DRV8824 logic ground
- PCA9685 ground
- motor power supply ground
- servo power supply ground

Without a shared ground, the control signals may behave unpredictably.

## 7. Prepare the Raspberry Pi operating system

### 7.1 Flash the SD card

Use Raspberry Pi Imager on your computer.

When you prepare the SD card:
- choose Raspberry Pi OS
- set the hostname to something descriptive, such as `afl-vialcapper`
- enable SSH
- set a username and password
- if needed, preconfigure network settings

A descriptive hostname is useful because it helps you identify the device later.

### 7.2 Boot the Pi

Insert the SD card into the Raspberry Pi.
Connect:
- Ethernet cable
- power
- any required motor power supplies, but keep the mechanism in a safe state

Wait for the Pi to boot.

### 7.3 Find the Pi on the network

If the Pi is connected by Ethernet, you need its IP address.

You can find it in several ways:
- from your router's device list
- by using a network scanner
- by connecting a monitor and keyboard to the Pi and running `hostname -I`
- by trying `ssh pi@afl-vialcapper.local` if local hostname resolution works on your network

If you log into the Pi locally or over SSH, run:

```bash
hostname -I
```

This prints the IP address. Write it down. You will use it later when connecting through the AFL API.

Example:

```bash
192.168.1.50
```

## 8. Verify SSH access

From your control computer, test SSH access:

```bash
ssh pi@afl-vialcapper.local
```

or, if hostname resolution does not work:

```bash
ssh pi@192.168.1.50
```

If this works, you know the Pi is reachable over the network.

To make future logins easier, copy your SSH key to the Pi:

```bash
ssh-copy-id pi@192.168.1.50
```

After that, you should be able to log in without typing the password every time.

## 9. Enable I2C on the Raspberry Pi

The PCA9685 uses I2C, so I2C must be enabled.

Run:

```bash
sudo raspi-config
```

Then go to:
- Interface Options
- I2C
- Enable

Reboot if prompted.

After rebooting, install I2C tools:

```bash
sudo apt update
sudo apt install -y i2c-tools
```

Then scan the I2C bus:

```bash
i2cdetect -y 1
```

If the PCA9685 is connected correctly, you should usually see address `40` in the table.

If you do not see the board:
- check SDA and SCL wiring
- check power and ground
- check that I2C is enabled
- check that the board address jumpers have not changed the default address

## 10. Install the AFL-automation software environment

There are two general ways to prepare a Raspberry Pi in this repository:

1. Use the Ansible deployment playbooks in [deploy/DEPLOY.md](/Users/knv2/Documents/codebase/AFL-automation/deploy/DEPLOY.md)
2. Install the environment manually

For a first-time hardware bring-up, manual installation is often easier to understand because you can see each step clearly.

### 10.1 Install basic system packages

On the Raspberry Pi, run:

```bash
sudo apt update
sudo apt install -y git python3-pip python3-venv vim screen
```

These packages give you:
- `git` for downloading the repository
- `python3-pip` for installing Python packages
- `python3-venv` for creating a virtual environment
- `vim` as a text editor
- `screen` for keeping long-running processes alive in a terminal session

### 10.2 Clone the repository

Choose a location in your home directory and clone AFL-automation:

```bash
cd ~
git clone https://github.com/usnistgov/AFL-automation.git
```

### 10.3 Create a Python virtual environment

A virtual environment keeps the Python packages for this project separate from the rest of the system.

Create it:

```bash
python3 -m venv ~/aflpy
```

Activate it:

```bash
source ~/aflpy/bin/activate
```

When the environment is active, your shell prompt usually changes to show the environment name.

### 10.4 Install AFL-automation into the environment

Run:

```bash
pip install -e ~/AFL-automation
```

The `-e` means editable install. That is useful during development because changes to the source code are picked up without reinstalling the package each time.

### 10.5 Install API server dependencies

Depending on the environment and package state, you may also need to install the API-related packages explicitly:

```bash
pip install "flask<2.3" flask_jwt_extended flask_cors requests pint waitress
```

### 10.6 Install hardware control packages

Install the packages needed for the PCA9685 and Raspberry Pi GPIO:

```bash
pip install adafruit-circuitpython-pca9685 adafruit-circuitpython-servokit adafruit-blinka RPi.GPIO
```

These packages are used for:
- talking to the PCA9685 over I2C
- controlling the servo
- controlling Raspberry Pi GPIO pins for the stepper driver

## 11. Understand where the API comes from in AFL-automation

AFL-automation uses two important concepts:

1. Driver
   The Driver is the Python class that knows how to control your specific hardware.

2. APIServer
   The APIServer is the web server that exposes the Driver methods over HTTP.

The relevant core files in this repository are:
- [AFL/automation/APIServer/Driver.py](/Users/knv2/Documents/codebase/AFL-automation/AFL/automation/APIServer/Driver.py)
- [AFL/automation/APIServer/APIServer.py](/Users/knv2/Documents/codebase/AFL-automation/AFL/automation/APIServer/APIServer.py)
- [AFL/automation/shared/launcher.py](/Users/knv2/Documents/codebase/AFL-automation/AFL/automation/shared/launcher.py)

The Driver contains methods such as:
- move up
- move down
- open gripper
- close gripper
- home
- status

The APIServer exposes those methods as network endpoints.

## 12. How commands are categorized in AFL-automation

AFL-automation distinguishes between two kinds of Driver methods.

### 12.1 Queued methods

Queued methods are actions that should go through the task queue.
These are usually real hardware actions.

Examples:
- move the stepper motor
- open the gripper
- close the gripper
- run a cap or decap sequence

Queued methods are useful because they prevent multiple hardware actions from colliding with each other.

### 12.2 Unqueued methods

Unqueued methods are immediate queries or lightweight actions.

Examples:
- ask for status
- read a current position value
- check whether the server is alive

These methods return quickly and do not need to wait in the hardware action queue.

## 13. Where the vial capper Driver should live

The Driver for this instrument should be added to the AFL-automation Python package, for example in a location such as:

- `AFL/automation/loading/`
- or another appropriate package directory used by your lab

The exact file name is up to you, but it should be descriptive, such as:

- `VialCapperDriver.py`
- `VialCapperDecapperDriver.py`

This guide does not include the Driver code itself, but the Driver should be responsible for:
- configuring GPIO pins for the DRV8824
- configuring the PCA9685 and servo channel
- converting requested travel distances into step counts
- opening and closing the gripper
- exposing high-level actions to the AFL API

## 14. How AFL starts a Driver as an API server

This repository includes a shared launcher in [AFL/automation/shared/launcher.py](/Users/knv2/Documents/codebase/AFL-automation/AFL/automation/shared/launcher.py).

That launcher is the standard way to start a Driver as an AFL API server.

When a Driver module is written to use the launcher, you can start it with a command like:

```bash
python -m AFL.automation.loading.VialCapperDriver
```

When that happens, the launcher will:
- create or load the global AFL config file in `~/.afl/config.json`
- determine which port the server should use
- create the APIServer
- attach the Driver to the server
- bind the server to the network
- start listening for HTTP requests

## 15. What network address the API uses

The API address has this form:

```text
http://<pi-ip-address>:<port>
```

For example:

```text
http://192.168.1.50:5052
```

This means:
- `192.168.1.50` is the Raspberry Pi IP address on the Ethernet network
- `5052` is the port number used by the vial capper API server

If the server is configured to bind to `0.0.0.0`, it will listen on all network interfaces on the Pi. That is the normal choice for a device that should be reachable from another computer on the network.

## 16. First run behavior and configuration files

When you run an AFL Driver module for the first time, AFL-automation may create configuration files under:

```text
~/.afl/
```

The most important one is:

```text
~/.afl/config.json
```

This file can store:
- the bind address
- port assignments
- driver-specific custom configuration
- system serial information
- optional Tiled configuration

A simple example configuration might look like this:

```json
{
  "owner_email": "",
  "system_serial": "VCAPPER01",
  "tiled_server": "",
  "tiled_api_key": "",
  "bind_address": "0.0.0.0",
  "ports": {
    "VialCapperDriver": 5052
  },
  "driver_custom_configs": {
    "VialCapperDriver": {
      "_classname": "AFL.automation.loading.VialCapperDriver.VialCapperDriver"
    }
  },
  "ca_status_enabled": false,
  "ca_status_ports": {}
}
```

You do not need to memorize this file. The important idea is that AFL uses it to remember how to launch the server.

## 17. Starting the API server on the Raspberry Pi

Once the Driver exists in the Python package and the environment is installed, activate the environment and start the module.

```bash
source ~/aflpy/bin/activate
python -m AFL.automation.loading.VialCapperDriver
```

If the Driver file has a different name or location, adjust the module path accordingly.

When the server starts successfully, it should begin listening on the configured port.

At that point, the Raspberry Pi is acting as a networked instrument controller.

## 18. Basic API endpoints you should know

AFL-automation provides several standard endpoints.

### 18.1 Check whether the server is alive

```text
GET /is_server_live
```

Example:

```text
http://192.168.1.50:5052/is_server_live
```

If the server is running, this should return something like `OK`.

### 18.2 Get general server information

```text
GET /get_info
```

This returns information about the server, queue, and Driver.

### 18.3 List queued commands

```text
GET /get_queued_commands
```

This tells you which hardware actions the Driver exposes through the queue.

### 18.4 List unqueued commands

```text
GET /get_unqueued_commands
```

This tells you which immediate query methods are available.

### 18.5 Call an unqueued Driver method

```text
GET /query_driver?r=<method_name>
```

For example, if the Driver exposes a `status` method:

```text
http://192.168.1.50:5052/query_driver?r=status
```

### 18.6 Queue a hardware action

```text
POST /enqueue
```

This is how you ask the instrument to perform a queued action such as moving the stepper or opening the gripper.

## 19. How to connect from another computer using the Pi IP address

The AFL Python client already supports connecting by IP address.

The client class is in [AFL/automation/APIServer/Client.py](/Users/knv2/Documents/codebase/AFL-automation/AFL/automation/APIServer/Client.py).

The important idea is simple:

You create a client object and pass the Raspberry Pi IP address and port.

Example:

```python
from AFL.automation.APIServer.Client import Client

capper = Client(ip="192.168.1.50", port="5052")
capper.login("tester")
```

After login, the client can query the server and enqueue hardware actions.

## 20. Example client-side usage without showing Driver code

Here is an example of how a control computer might talk to the vial capper API.

```python
from AFL.automation.APIServer.Client import Client

capper = Client(ip="192.168.1.50", port="5052", username="tester")

print(capper.get_unqueued_commands())
print(capper.get_queued_commands())
print(capper.query_driver(r="status"))
```

If the Driver has been written to expose methods dynamically through the client, you may also be able to call methods directly after login.

For example, if the Driver exposes methods such as `move_down`, `move_up`, `grip_open`, and `grip_close`, the client may be able to call them like this:

```python
from AFL.automation.APIServer.Client import Client

capper = Client(ip="192.168.1.50", port="5052", username="tester")

capper.move_down(distance_mm=10.0)
capper.grip_close()
capper.move_up(distance_mm=10.0)
capper.grip_open()
```

Whether these exact method names exist depends on how the Driver is implemented.

## 21. Example manual HTTP testing with curl

Sometimes it is useful to test the API without writing a Python script.

### 21.1 Log in

```bash
curl -X POST http://192.168.1.50:5052/login \
  -H "Content-Type: application/json" \
  -d '{"username":"tester","password":"domo_arigato"}'
```

This returns a token.

### 21.2 Check server info

```bash
curl http://192.168.1.50:5052/get_info \
  -H "Authorization: Bearer <TOKEN>"
```

### 21.3 Ask for Driver status

```bash
curl "http://192.168.1.50:5052/query_driver?r=status" \
  -H "Authorization: Bearer <TOKEN>"
```

### 21.4 Queue a hardware action

```bash
curl -X POST http://192.168.1.50:5052/enqueue \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"task_name":"move_down","distance_mm":10.0}'
```

The exact task names depend on the Driver implementation.

## 22. Recommended first hardware tests

Before trying a full cap or decap sequence, test each subsystem separately.

### 22.1 Test the PCA9685 is visible

Run:

```bash
i2cdetect -y 1
```

Make sure the PCA9685 appears.

### 22.2 Test the servo alone

Before involving AFL, verify that the servo can open and close the gripper safely.

Check:
- the servo moves in the expected direction
- the gripper does not bind
- the servo does not stall or buzz excessively
- the power supply remains stable

### 22.3 Test the stepper alone

Before involving AFL, verify that the stepper can move the lead screw up and down safely.

Check:
- the direction is correct
- the travel is smooth
- the motor does not skip badly
- the mechanism does not hit hard stops unexpectedly

### 22.4 Test very small motions first

Start with:
- small vertical moves
- short servo motions
- low speed
- no vial present

This reduces the chance of damaging the mechanism.

## 23. Recommended safety features for a real instrument

A real instrument should include more than just basic motion control.

Strongly recommended additions are:

1. A homing switch or limit switch
   This gives the system a known reference position.

2. Software travel limits
   The Driver should refuse to move beyond safe bounds.

3. A safe startup state
   On startup, the gripper and Z axis should move to a known safe condition.

4. An emergency stop method
   There should be a way to stop motion quickly.

5. Mechanical clearance checks
   Make sure the gripper cannot crash into the vial holder, frame, or table.

6. Conservative default speeds
   Fast motion is tempting, but slow motion is safer during bring-up.

## 24. Important mechanical note about screwing and unscrewing

This guide is based on the hardware description that includes:
- one stepper motor for vertical motion
- one servo motor for opening and closing the gripper

That combination is enough for:
- approaching a vial
- gripping a cap or vial feature
- lifting
- lowering
- releasing

However, true threaded capping and decapping usually also require rotational motion.

If your instrument is meant to literally screw and unscrew threaded caps, then one of the following must also be true:
- the gripper itself rotates
- the vial rotates
- there is another motorized axis that provides twisting motion

If no rotational mechanism exists, then the instrument can still act as a vertical gripper manipulator, but not a true screw-on or screw-off capper in the mechanical sense.

## 25. Running the server automatically on boot

Once the system works manually, it is a good idea to make it start automatically when the Pi boots.

A common way to do this on Linux is with a `systemd` service.

A typical service file might look like this:

```ini
[Unit]
Description=AFL Vial Capper API
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/AFL-automation
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/pi/aflpy/bin/python -m AFL.automation.loading.VialCapperDriver
Restart=always

[Install]
WantedBy=multi-user.target
```

Save this as something like:

```text
/etc/systemd/system/vialcapper.service
```

Then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable vialcapper
sudo systemctl start vialcapper
sudo systemctl status vialcapper
```

This makes the API server start automatically after reboot.

## 26. Troubleshooting checklist

If something does not work, go through this list carefully.

### 26.1 The Pi is not reachable over Ethernet

Check:
- the Ethernet cable
- the network switch or router
- the Pi IP address using `hostname -I`
- whether you can `ping` the Pi from the control computer
- whether SSH works

### 26.2 The PCA9685 does not appear in `i2cdetect`

Check:
- I2C is enabled
- SDA and SCL are not swapped
- the board has power
- ground is connected
- the board address is correct

### 26.3 The servo twitches or resets the Pi

Check:
- the servo has its own adequate power supply
- the grounds are shared
- the power supply can provide enough current

### 26.4 The stepper motor vibrates but does not move correctly

Check:
- motor coil wiring
- current limit on the DRV8824
- step pulse timing
- microstepping settings
- mechanical binding in the lead screw assembly

### 26.5 The API server starts but the client cannot connect

Check:
- the server is running on the Pi
- the correct port is being used
- the bind address is `0.0.0.0`
- the Pi firewall or network policy is not blocking the port
- you are using the correct Pi IP address

### 26.6 The client connects but a command fails

Check:
- the Driver actually exposes that method
- the method is categorized correctly as queued or unqueued
- the task name matches exactly
- the Driver dependencies are installed on the Pi

## 27. Practical bring-up sequence

A good bring-up order is:

1. Wire the hardware carefully.
2. Verify shared ground.
3. Boot the Pi and confirm Ethernet connectivity.
4. Enable I2C.
5. Confirm the PCA9685 appears in `i2cdetect`.
6. Install AFL-automation and dependencies.
7. Verify the servo works in a simple standalone test.
8. Verify the stepper works in a simple standalone test.
9. Add the vial capper Driver to AFL-automation.
10. Start the Driver module with `python -m ...`.
11. Test `/is_server_live`.
12. Test `/get_queued_commands` and `/get_unqueued_commands`.
13. Test `status`.
14. Test very small motion commands.
15. Only after that, test higher-level cap or decap sequences.

## 28. Summary

To control a Raspberry Pi based vial capper and decapper through AFL-automation over Ethernet, you need to do three big things:

1. Build and wire the hardware correctly.
   The Pi talks to the DRV8824 through GPIO and to the PCA9685 through I2C.

2. Install and run AFL-automation on the Pi.
   The Pi hosts the API server and runs the hardware-specific Driver.

3. Connect from another computer using the Pi IP address.
   The control computer uses the AFL client or direct HTTP requests to send commands to the Pi.

The key idea is simple:

The Raspberry Pi is the instrument controller.
The Ethernet-connected computer is the remote user.
The AFL API is the bridge between them.

Once the Driver is implemented and the server is running, the instrument can be controlled over the network using the Pi's IP address and port.
