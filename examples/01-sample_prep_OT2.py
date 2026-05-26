"""
Test script for preparing samples on the OT2 using the OT2Prepare driver. 
This example demonstrates 
how to set up the robot, 
define stocks and targets, 
and execute a preparation protocol that includes temperature control and shaking.

You require the OT2 to be connected via ethernet (USB-B or LAN) with atleast the following firmware version:
    - Firmware Version v1.1.0-25e5cea
    - Supported Protocol API Versions v2.0 - v2.28

You are going to need the IP address of your OT2, which you can find in the Opentrons app under Network settings (use GPT to find it if you have trouble). 
Update the `robot_ip` field in the driver initialization below with your OT2's IP address. The port should be `31950` by default unless you have changed it.

"""

from AFL.automation.prepare.OT2Prepare import OT2Prepare

import numpy as np
import time 
import json
import requests

# Create the driver instance
driver = OT2Prepare(
    overrides={
        "robot_ip": "169.254.59.185",
        "robot_port": "31950",
    }
)
driver.reset_stocks()
driver.reset_deck() # necssary to remove cache of modules and labware
driver.reset()

# Tip racks and Pipettes (Gen 2 P1000 and gen 2 P20)
driver.load_labware(name="geb_96_tiprack_1000ul", slot="10")
driver.load_instrument(name="p1000_single_gen2", mount="right", tip_rack_slots=["10"])

driver.load_labware(name="geb_96_tiprack_10ul", slot="11")
driver.load_instrument(name="p20_single_gen2", mount="left", tip_rack_slots=["11"])

# Load custom labware from JSON
with open('./labware/ice_slurry_holder_20ml_3x2.json', 'r') as f:
    custom_labware_def = json.load(f)
driver.load_labware(
    name='ice_slurry_holder',
    slot='2',
    labware_json = custom_labware_def
)

# Load heater shaker module
heater_shaker_id = driver.load_module("heaterShakerModuleV1", slot="4")

driver.unlatch_shaker(module_id=heater_shaker_id)
driver.load_labware(
    name="opentrons_96_deep_well_adapter",
    slot="4",
    module=heater_shaker_id,
)
driver.load_labware(
    name="nest_96_wellplate_2ml_deep",
    slot="4",
    module=heater_shaker_id,
)
driver.latch_shaker(module_id=heater_shaker_id)

temp_module_id = driver.load_module("temperatureModuleV1", slot="3")
# Load custom vial holder labware onto the temperature module
with open('./labware/5ml_vial_holder_1x1_hightemp.json', 'r') as f:
    vial_holder_def = json.load(f)
driver.load_labware(
    name='vial_holder',
    slot='3',
    labware_json = vial_holder_def,
    module=temp_module_id,
)

driver.reset_stocks()
driver.add_component(name="H2O", formula="H2O", density="1.0 g/ml")
driver.add_component(name="YCl3", formula="YCl3")
driver.add_component(name="BSA")  # formula optional if you only use mg/mL

driver.add_stock({
    "name": "stock_BSA",
    "location": "2A1",
    "concentrations": {"BSA": "200 mg/ml"},
    "volumes": {"H2O": "20 ml"},
    "total_volume": "20 ml",
    "solutes": ["BSA"],
})

driver.add_stock({
    "name": "stock_YCl3",
    "location": "2A2",
    "molarities": {"YCl3": "1 mol/L"},
    "volumes": {"H2O": "10 ml"},
    "total_volume": "10 ml",
    "solutes": ["YCl3"],
})

driver.add_stock({
    "name": "stock_H2O",
    "location": "2A3",
    "volumes": {"H2O": "20 ml"},
    "total_volume": "20 ml",
})

target = {
    "name": "bsa_ycl3_sample",
    "concentrations": {"BSA": "175 mg/ml"},
    "molarities": {"YCl3": "43 mmol/L"},
    "volumes": {"H2O": "1 ml"},
    "total_volume": "1 ml",
    "solutes": ["BSA", "YCl3"],
    "location": "4A1",
}

def set_temp_module_temperature(
    driver,
    module_id,
    temperature_c,
    timeout_s=600,
    wait=True,
    tolerance_c=1.0,
    poll_s=2,
):
    driver._execute_atomic_command(
        "temperatureModule/setTargetTemperature",
        params={"moduleId": module_id, "celsius": float(temperature_c)},
        wait_until_complete=False,
        timeout=timeout_s,
    )

    if not wait:
        return None, float(temperature_c)

    start = time.time()
    while time.time() - start < timeout_s:
        response = requests.get(
            url=f"{driver.base_url}/modules",
            headers=driver.headers,
            timeout=30,
        )
        response.raise_for_status()

        modules = response.json().get("modules", [])
        temp_module = next((m for m in modules if m.get("id") == module_id), None)
        if temp_module is None:
            raise RuntimeError(f"Temperature module {module_id} not found")

        data = temp_module.get("data", {})
        current_temp = data.get("currentTemp")
        target_temp = data.get("targetTemp")

        print(f"Temp module current: {current_temp} C, target: {target_temp} C")

        if current_temp is not None and abs(current_temp - float(temperature_c)) <= tolerance_c:
            return current_temp, target_temp

        time.sleep(poll_s)

    raise TimeoutError(
        f"Temperature module did not reach {temperature_c} C within {timeout_s} s"
    )

def deactivate_temp_module(driver, module_id, timeout_s=120, wait=True):
    return driver._execute_atomic_command(
        "temperatureModule/deactivate",
        params={"moduleId": module_id},
        wait_until_complete=wait,
        timeout=timeout_s,
    )

feasible = driver.is_feasible(target)[0]
print("Feasible solution:", feasible)

result, dest = driver.prepare(target, dest="3A1")
print("Prepared at:", dest)
print("Planned mass transfers:", result["planned_mass_transfers"])
print("Executed transfers:", result["executed_transfers"])

# Gently mix the prepared sample in the heater-shaker plate
driver.set_shake(400, module_id=heater_shaker_id)
time.sleep(5)
driver.stop_shake(module_id=heater_shaker_id)

# Step through temperatures
for temp_c in [30, 60, 80]:
    print(f"Setting sample temperature to {temp_c} C")
    set_temp_module_temperature(driver, temp_module_id, temp_c)

deactivate_temp_module(driver, temp_module_id)


