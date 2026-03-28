import yaml
import RPi.GPIO as GPIO
import os

class GpioController:
    def __init__(self, config_file="config.yaml"):
        self.aliases = {}
        self.pullup_pulldown = {}
        self.pins_initialized = set()  # Track initialized GPIO pins
        self.load_aliases(config_file)

    def load_aliases(self, config_file):
        """Load GPIO port aliases and pull-up/pull-down configuration from YAML."""
        config_path = os.path.join(os.path.dirname(__file__), config_file)
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
            
            # Default to empty dictionaries if keys are missing
            self.aliases = config.get("gpio_aliases", {})
            self.pullup_pulldown = config.get("gpio_pull", {})

        # Check if there are no aliases defined and exit early if necessary
        if not self.aliases:
            print("No GPIO aliases defined in config. Skipping GPIO setup.")
            return

        # Set up GPIO pins and their pull configurations once, based on config
        GPIO.setmode(GPIO.BCM)  # Set GPIO mode at the start

        for alias, port in self.aliases.items():
            pull = self.pullup_pulldown.get(alias, None)
            if pull == "up":
                GPIO.setup(port, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            elif pull == "down":
                GPIO.setup(port, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            else:
                GPIO.setup(port, GPIO.OUT)

            self.pins_initialized.add(port)


    def set_gpio_state(self, port_or_alias, state):
        """Set the specified GPIO port or alias to the given state (on/off)."""
        port = self.aliases.get(port_or_alias, port_or_alias)  # Resolve alias if exists

        # Set the GPIO output state (no pull configuration here, already handled)
        if state.lower() == "on":
            GPIO.output(port, GPIO.HIGH)  # Set port to HIGH
        elif state.lower() == "off":
            GPIO.output(port, GPIO.LOW)  # Set port to LOW
        else:
            print(f"Invalid state: {state}. Use 'on' or 'off'.")
