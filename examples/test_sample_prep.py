from AFL.automation.prepare.OT2Prepare import OT2Prepare

import numpy as np
import time 
import json

# Create the driver instance
driver = OT2Prepare() # assumes the OT2 server is running with default settings (e.g.: via Andon)
driver.reset_stocks()
driver.reset_deck() # necssary to remove cache of modules and labware
driver.reset()

# Tip racks and Pipettes (Gen 1 P300 and gen 2 P20)
driver.load_labware(name="opentrons_96_tiprack_300ul", slot="7")
driver.load_instrument(name="p300_single", mount="right", tip_rack_slots=["7"])

driver.load_labware(name="opentrons_96_tiprack_20ul", slot="8")
driver.load_instrument(name="p20_single_gen2", mount="left", tip_rack_slots=["8"])

# Load custom labware from JSON
with open('./ice_slurry_holder_20ml_3x2.json', 'r') as f:
    custom_labware_def = json.load(f)
driver.load_labware(
    name='ice_slurry_holder',
    slot='1',
    labware_json = custom_labware_def
)

# Load heater shaker module
heater_shaker_id = driver.load_module("heaterShakerModuleV1", slot="4")

driver.unlatch_shaker(module_id=heater_shaker_id)
driver.load_labware(
    name="nest_96_wellplate_2ml_deep",
    slot="4",
    module=heater_shaker_id,
)
driver.latch_shaker(module_id=heater_shaker_id)

temp_module_id = driver.load_module("temperatureModuleV1", slot="3")

driver.load_labware(
    name="opentrons_24_aluminumblock_nest_1.5ml_snapcap",
    slot="3",
    module=temp_module_id,
)

driver.reset_stocks()
driver.add_component(name="H2O", formula="H2O", density="1.0 g/ml")
driver.add_component(name="YCl3", formula="YCl3")
driver.add_component(name="BSA")  # formula optional if you only use mg/mL

driver.add_stock({
    "name": "stock_BSA",
    "location": "1A1",
    "concentrations": {"BSA": "200 mg/ml"},
    "volumes": {"H2O": "20 ml"},
    "total_volume": "20 ml",
    "solutes": ["BSA"],
})

driver.add_stock({
    "name": "stock_YCl3",
    "location": "1A2",
    "molarities": {"YCl3": "1 mol/L"},
    "volumes": {"H2O": "10 ml"},
    "total_volume": "10 ml",
    "solutes": ["YCl3"],
})

driver.add_stock({
    "name": "stock_H2O",
    "location": "1A3",
    "volumes": {"H2O": "20 ml"},
    "total_volume": "20 ml",
})

target = {
    "name": "bsa_ycl3_sample",
    "concentrations": {"BSA": "175 mg/ml"},
    "molarities": {"YCl3": "9 mmol/L"},
    "volumes": {"H2O": "1 ml"},
    "total_volume": "1 ml",
    "solutes": ["BSA", "YCl3"],
    "location": "1B1",
}

feasible = driver.is_feasible(target)[0]
print("Feasible solution:", feasible)

def wait_for_temperature(driver, target_c, tolerance_c=1.0, timeout_s=600, poll_s=2):
    start = time.time()
    while time.time() - start < timeout_s:
        current_temp, target_temp = driver.get_shaker_temp()
        print(f"Current: {current_temp} C, Target: {target_temp} C")
        if current_temp is not None and abs(current_temp - target_c) <= tolerance_c:
            return
        time.sleep(poll_s)
    raise TimeoutError(f"Heater-shaker did not reach {target_c} C within {timeout_s} s")


result, dest = driver.prepare(target, dest="4A1")
print("Prepared at:", dest)
print("Planned mass transfers:", result["planned_mass_transfers"])
print("Executed transfers:", result["executed_transfers"])

# Gently mix the prepared sample in the heater-shaker plate
driver.set_shake(300, module_id=heater_shaker_id)
time.sleep(5)
driver.stop_shake(module_id=heater_shaker_id)

def set_temp_module_temperature(driver, module_id, temperature_c, timeout_s=600, wait=True):
    return driver._execute_atomic_command(
        "temperatureModule/setTargetTemperature",
        params={"moduleId": module_id, "celsius": float(temperature_c)},
        wait_until_complete=wait,
        timeout=timeout_s,
    )

def deactivate_temp_module(driver, module_id, timeout_s=120, wait=True):
    return driver._execute_atomic_command(
        "temperatureModule/deactivate",
        params={"moduleId": module_id},
        wait_until_complete=wait,
        timeout=timeout_s,
    )
# Step through temperatures
for temp_c in [30, 60, 80]:
    print(f"Setting sample temperature to {temp_c} C")
    set_temp_module_temperature(driver, temp_module_id, temp_c)
    deactivate_temp_module(driver, temp_module_id)


