import threading
import logging
import sys
import os
import json
import yaml
import time
import paho.mqtt.client as mqtt

from .core import AquaLogic
from .states import States
from .mqtt_manager import MQTT_Manager
from .Gpio import GpioController


# Configure logging
logging.basicConfig(level=logging.INFO)

# Load configuration from YAML file
config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
with open(config_path, 'r') as file:
    config = yaml.safe_load(file)

# Retrieve connection parameters from config
rs485_serial_port = config['rs485_connection'].get('rs485_serial_port')
host = config['rs485_connection'].get('host')
port = config['rs485_connection'].get('port')

# Read Gpio aliases from config.yaml
gpio_aliases = config.get('gpio_aliases', {})

# Validate connection configuration
if rs485_serial_port:
    print(f"Connecting via serial port: {rs485_serial_port}")
elif host and port:
    print(f"Connecting via host {host} and port {port}")
else:
    raise ValueError("Configuration must include either 'serial_port' or both 'host' and 'port'.")

# Initialize AquaLogic panel
PANEL = AquaLogic()
if rs485_serial_port:
    PANEL.connect_serial(rs485_serial_port)
else:
    PANEL.connect(host, int(port))
print('Connected!')

# Initialize GPIO Controller
gpio_controller = GpioController()

# Initialize MQTT manager
manager = MQTT_Manager(config_path, callback=lambda button: button_received(button))
manager.start()

# Global variables
previous_pool_status = {}

def button_received(button):
    try:
        pool_status = get_status_json(PANEL) 
        op_mode = pool_status.get("OP_MODE")
        print (f"interpreted op mode = {op_mode}")
        if button == "POOL_DISTINCT":
            pool_distinct(op_mode)
        elif button == "SPA_DISTINCT":
            spa_distinct(op_mode)
        elif button == "SPILLOVER_DISTINCT":
            spillover_distinct(op_mode)
        elif button.endswith("_ON"):
            state = States[button[:-3]]
            PANEL.set_state(state, True)
        elif button.endswith("_OFF"):
            state = States[button[:-4]]
            PANEL.set_state(state, False)
        else:
            state = States[button]
            PANEL.set_state(state, not PANEL.get_state(state))
    except KeyError:
        print(f"Invalid State name {button}")
    except ValueError as e:
        print(e)

def pool_distinct(op_mode):
    """Handle the POOL_DISTINCT command."""
    if op_mode == "SPA":
        state = States["SPA"]
        PANEL.set_state(state, not PANEL.get_state(state))   
    elif op_mode == "SPILLOVER":
        state = States["SPA"]
        print (f"{state} was pressed")
        PANEL.set_state(state, not PANEL.get_state(state))

def spa_distinct(op_mode):
    """Handle the SPA_DISTINCT command."""
    if op_mode == "POOL":
        state = States["SPA"]
        PANEL.set_state(state, not PANEL.get_state(state))    
    elif op_mode == "SPILLOVER":
        state = States["POOL"]
        PANEL.set_state(state, not PANEL.get_state(state)) 

def spillover_distinct(op_mode):
    """Handle the SPILLOVER_DISTINCT command."""
    if op_mode == "POOL":
        state = States["SPA"]
        PANEL.set_state(state, not PANEL.get_state(state))
        
        # Loop until op_mode changes to "SPA" or timeout occurs
        start_time = time.time()
        while True:
            pool_status = get_status_json(PANEL)
            op_mode = pool_status.get("OP_MODE")
            if op_mode == "SPA" or time.time() - start_time > 10:
                break
            time.sleep(1)
        
        state = States["POOL"]
        PANEL.set_state(state, not PANEL.get_state(state))    
    elif op_mode == "SPA":
        state = States["POOL"]
        PANEL.set_state(state, not PANEL.get_state(state))

def get_status_json(panel):
    """
    Generate a JSON-like dictionary containing the current status of the AquaLogic panel.
    
    Args:
        panel (AquaLogic): The AquaLogic panel instance to extract status from.
    
    Returns:
        dict: A dictionary representing the current pool status.
    """
    # Initialize the pool status with default values
    pool_status = {
        "air_temp": panel.air_temp,
        "pool_temp": panel.pool_temp,
        "spa_temp": panel.spa_temp,
        "pool_chlorinator": panel.pool_chlorinator,
        "spa_chlorinator": panel.spa_chlorinator,
        "salt_level": panel.salt_level,
        "check_system_msg": panel.check_system_msg,
        "status": panel.status,
        "pump_speed": panel.pump_speed,
        "pump_power": panel.pump_power,
        "is_metric": panel.is_metric,
        "is_heater_enabled": panel.is_heater_enabled,
        "is_super_chlorinate_enabled": panel.is_super_chlorinate_enabled,
        "HEATER_1": 0,
        "VALVE_3": 0,
        "CHECK_SYSTEM": 0,
        "POOL": 0,
        "SPA": 0,
        "FILTER": 0,
        "LIGHTS": 0,
        "AUX_1": 0,
        "AUX_2": 0,
        "SERVICE": 0,
        "AUX_3": 0,
        "AUX_4": 0,
        "AUX_5": 0,
        "AUX_6": 0,
        "VALVE_4": 0,
        "SPILLOVER": 0,
        "SYSTEM_OFF": 0,
        "AUX_7": 0,
        "AUX_8": 0,
        "AUX_9": 0,
        "AUX_10": 0,
        "AUX_11": 0,
        "AUX_12": 0,
        "AUX_13": 0,
        "AUX_14": 0,
        "SUPER_CHLORINATE": 0,
        "HEATER_AUTO_MODE": 0,
        "FILTER_LOW_SPEED": 0,
        "OP_MODE": "POOL"
    }

    # Update pool_status values based on panel states
    for key in pool_status:
        state_enum = getattr(States, key, None)
        if state_enum in panel.states():
            pool_status[key] = 1    
            
    #Extend PS-4 with Op_Mode
    # Update OP_MODE based on Pool and Spa values
    if pool_status["SPA"] == 1 and pool_status["POOL"] == 0:
        pool_status["OP_MODE"] = "SPA"
        op_mode = "SPA"
    elif pool_status["POOL"] == 1 and pool_status["SPA"] == 1:
        pool_status["OP_MODE"] = "SPILLOVER"
        op_mode = "SPILLOVER"
    elif pool_status["POOL"] == 1 and pool_status["SPA"] == 0:
        pool_status["OP_MODE"] = "POOL"
        op_mode = "POOL"

    return pool_status


def _data_changed(panel):
    global previous_pool_status

    #print(f"Pool Temp: {panel.pool_temp}")
    #print(f"Air Temp: {panel.air_temp}")
    #print(f"Pump Speed: {panel.pump_speed}")
    #print(f"Pump Power: {panel.pump_power}")
    #print(f"States: {panel.states()}")

    #if panel.get_state(States.CHECK_SYSTEM):
        #print(f"Check System: {panel.check_system_msg}")

    pool_status = get_status_json(panel)

    # Update GPIO states
    if not gpio_aliases:  # Check if gpio_aliases is None or empty
        print("No GPIO aliases defined. Skipping GPIO state updates.")
    else:
        for key, value in pool_status.items():
            if key in gpio_aliases:
                gpio_alias = gpio_aliases[key]
                if key in previous_pool_status and previous_pool_status[key] == value:
                    continue  # Skip updating if state hasn't changed
                gpio_state = "on" if value else "off"
                gpio_controller.set_gpio_state(gpio_alias, gpio_state)
                print(f"Set GPIO {gpio_alias} to {gpio_state}.")


    # Handle triggers
    for trigger in config.get('triggers', []):
        trigger_state = trigger.get('trigger_state')
        trigger_value = trigger.get('trigger_value')
        target_state = trigger.get('target_state')
        target_value = trigger.get('target_value')

        if trigger_state in pool_status:
            current_value = pool_status[trigger_state]
            previous_value = previous_pool_status.get(trigger_state)

            if previous_value is not None and current_value != previous_value:
                if current_value == trigger_value:
                    target_enum = getattr(States, target_state, None)
                    if target_enum is not None:
                        PANEL.set_state(target_enum, target_value)
                        print(f"Triggered {target_state} to {target_value} based on {trigger_state} change from {previous_value} to {current_value}")

    previous_pool_status = pool_status.copy()

    # Publish pool status via MQTT
    manager.publish_status(pool_status)
    #print("Payload sent to StatusTopic from MQTTManager")
    manager.publish_LcdText(panel.LcdText)

# Start panel data processing thread
READER_THREAD = threading.Thread(target=PANEL.process, args=[_data_changed])
READER_THREAD.start()

# Handle user input in the main thread
while True:
    line = input()
    try:
        state = States[line]
        PANEL.set_state(state, not PANEL.get_state(state))
    except KeyError:
        print(f"Invalid State name {line}")

