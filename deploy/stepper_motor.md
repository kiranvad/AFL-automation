# Step-by-Step Guide: Wiring a Haydon 26844-05-067ENG Linear Stepper Motor to a Raspberry Pi Using a DRV8824

This guide assumes you have:

- Raspberry Pi
- DRV8824 stepper driver
- Haydon 26844-05-067ENG motor
- Breadboard
- Jumper wires
- External DC power supply (typically 12 V)
- 100 µF electrolytic capacitor

The goal is to make the actuator move in and out under Raspberry Pi control.

---

# Before You Start

## Important Fact About Your Motor

The Haydon 26844-05-067ENG is a **captive linear actuator**.

That means:

- The internal motor rotates.
- The lead screw does **not** rotate.
- The lead screw moves in and out.

So when testing, expect **linear motion**, not visible shaft rotation.

---

# Step 1 — Identify the Driver Pins

Locate the following labels on the DRV8824.

## Logic Side

```text
STEP
DIR
ENABLE
MODE0
MODE1
MODE2
RESET
SLEEP
GND
```

## Motor Power Side

```text
VMOT
GND
A1
A2
B1
B2
```

---

# Step 2 — Connect the Motor to the Driver

Earlier you identified the two motor coils using the multimeter.

You should have:

```text
Coil A = two wires
Coil B = two wires
```

## Connect Coil A

Take the two wires belonging to Coil A.

Connect them to:

```text
A1
A2
```

on the DRV8824.

## Connect Coil B

Take the two wires belonging to Coil B.

Connect them to:

```text
B1
B2
```

on the DRV8824.

---

# Step 3 — Create a Ground Bus

This will be the shared ground for the entire system.

## Locate Raspberry Pi Pin 39

Pin 39 is a GND pin.

Connect:

```text
Pi Pin 39
      ↓
Breadboard Row
```

This row becomes your:

```text
GND BUS
```

## Extend the GND Bus

Take another jumper wire.

Connect:

```text
GND BUS Row
      ↓
Empty Breadboard Rail
```

Now you have a long accessible ground rail.

---

# Step 4 — Connect Raspberry Pi to the Driver

## STEP Signal

Connect:

```text
Pi Physical Pin 38
(GPIO20)
        ↓
DRV8824 STEP
```

## DIR Signal

Connect:

```text
Pi Physical Pin 40
(GPIO21)
        ↓
DRV8824 DIR
```

## Driver Ground

Connect:

```text
DRV8824 GND
        ↓
GND BUS
```

---

# Step 5 — Supply 3.3 V to RESET and SLEEP

## Locate Raspberry Pi Pin 1

Pin 1 provides:

```text
3.3 V
```

## Create a 3.3 V Row

Connect:

```text
Pi Pin 1
     ↓
Breadboard Row
```

This becomes your:

```text
3.3 V ROW
```

## Connect RESET

Connect:

```text
DRV8824 RESET
        ↓
3.3 V ROW
```

## Connect SLEEP

Connect:

```text
DRV8824 SLEEP
        ↓
3.3 V ROW
```

Now:

```text
RESET = HIGH
SLEEP = HIGH
```

which keeps the driver awake.

---

# Step 6 — Configure Full-Step Mode

For initial testing, use full-step mode.

## MODE0

Connect:

```text
MODE0
  ↓
GND BUS
```

## MODE1

Connect:

```text
MODE1
  ↓
GND BUS
```

## MODE2

Connect:

```text
MODE2
  ↓
GND BUS
```

---

# Step 7 — Enable the Driver

Connect:

```text
ENABLE
   ↓
GND BUS
```

This keeps the motor outputs enabled.

---

# Step 8 — Connect Motor Power

## Positive Power

Connect:

```text
Power Supply +
       ↓
VMOT
```

## Negative Power

Connect:

```text
Power Supply -
       ↓
GND BUS
```

---

# Step 9 — Install the Capacitor

Locate the capacitor.

The side with the stripe is the negative side.

## Positive Capacitor Lead

Connect:

```text
Capacitor +
      ↓
VMOT
```

## Negative Capacitor Lead

Connect:

```text
Capacitor -
      ↓
GND BUS
```

Place it physically close to the driver.

---

# Step 10 — Set the Current Limit

For the Haydon 26844-05-067ENG:

- Rated current ≈ 340 mA RMS/phase

Recommended target:

```text
VREF ≈ 0.55–0.56 V
```

### Measure VREF

1. Set multimeter to DC Volts.
2. Black probe → GND near VMOT or PSU negative.
3. Red probe → metal screw on the DRV8824 potentiometer.
4. Adjust the potentiometer slowly until VREF is approximately 0.56 V.

---

# Step 11 — Final Wiring Checklist

Verify every item below.

### Motor

```text
Coil A → A1, A2
Coil B → B1, B2
```

### Raspberry Pi

```text
Pin 38 → STEP
Pin 40 → DIR
Pin 39 → GND
Pin 1  → RESET
Pin 1  → SLEEP
```

### Driver Configuration

```text
MODE0 → GND
MODE1 → GND
MODE2 → GND
ENABLE → GND
```

### Power

```text
PSU + → VMOT
PSU - → GND
```

### Capacitor

```text
Capacitor + → VMOT
Capacitor - → GND
```

---

# Step 12 — Power-Up Sequence

Always power things in this order:

### First

Power the Raspberry Pi.

Wait until it finishes booting.

### Second

Turn on the motor power supply.

---

# Step 13 — Create a Test Program

On the Raspberry Pi:

```bash
nano actuator_test.py
```

Paste:

```python
import RPi.GPIO as GPIO
import time

GPIO.setwarnings(False)

STEP_PIN = 20   # Physical Pin 38
DIR_PIN = 21    # Physical Pin 40

GPIO.setmode(GPIO.BCM)

GPIO.setup(STEP_PIN, GPIO.OUT)
GPIO.setup(DIR_PIN, GPIO.OUT)

GPIO.output(DIR_PIN, GPIO.HIGH)

try:

    for i in range(100):

        GPIO.output(STEP_PIN, GPIO.HIGH)
        time.sleep(0.01)

        GPIO.output(STEP_PIN, GPIO.LOW)
        time.sleep(0.01)

finally:

    GPIO.cleanup()
```

Save:

```text
CTRL + O
Enter
CTRL + X
```

---

# Step 14 — Run the Test

Run:

```bash
python3 actuator_test.py
```

---

# Expected Result

Because this is a captive linear actuator:

You should see:

```text
Lead screw moves outward
```

or

```text
Lead screw moves inward
```

depending on the DIR setting.

You should **not** expect the lead screw itself to spin.

---

# Step 15 — Reverse Direction

Change:

```python
GPIO.output(DIR_PIN, GPIO.HIGH)
```

to:

```python
GPIO.output(DIR_PIN, GPIO.LOW)
```

Run again:

```bash
python3 actuator_test.py
```

The lead screw should move in the opposite direction.

---

# Step 16 — If Nothing Moves

Check these in order:

1. VMOT has power from the external supply.
2. RESET and SLEEP are connected to 3.3 V.
3. ENABLE is connected to GND.
4. All grounds are connected together.
5. Coil A and Coil B are correctly identified.
6. STEP is connected to Pin 38 (GPIO20).
7. DIR is connected to Pin 40 (GPIO21).

If all of those are correct, the actuator should respond to the test program.