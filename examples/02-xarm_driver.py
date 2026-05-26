from AFL.automation.manipulate.XArmCobot import XArmCobot
import time

manupulator = XArmCobot(
    overrides={
        "ip": "192.168.1.201"
    }
)