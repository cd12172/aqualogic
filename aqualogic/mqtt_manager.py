import yaml
import paho.mqtt.client as mqtt
import json


class MQTT_Manager:
    def __init__(self, config_path, callback):
        self.config = self.load_config(config_path)
        self.mqtt_server = self.config['mqtt']['server']
        self.mqtt_port = self.config['mqtt']['port']
        self.mqtt_username = self.config['mqtt'].get('username')
        self.mqtt_password = self.config['mqtt'].get('password')
        self.status_topic = self.config['mqtt']['StatusTopic']
        self.command_topic = self.config['mqtt']['IncomingCommandTopic']
        self.LcdTextTopic = self.config['mqtt']['PoolLcdTopic']
        self.callback = callback
        self.client = mqtt.Client()
        if self.mqtt_username:
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)

    def load_config(self, config_path):
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected successfully to {self.mqtt_server} on port {self.mqtt_port}")
            # Subscribe only to IncomingCommandTopic
            client.subscribe(self.command_topic)
        else:
            print(f"Failed to connect, return code {rc}")

    def on_message(self, client, userdata, msg):
        print(f"Received command on topic {msg.topic}: {msg.payload.decode()}")
                # Call the callback function
        if self.callback:
            self.callback(msg.payload.decode())

    def publish_status(self, pool_status):
        """
        Publishes the given pool_status object to the StatusTopic.
        The pool_status should be a dictionary or an object that can be serialized into JSON.
        """
        # Convert the pool_status object to a JSON string
        status_payload = json.dumps(pool_status)
        self.client.publish(self.status_topic, status_payload)
        # print(f"Published to {self.status_topic}: {status_payload}")

    def publish_LcdText(self, text):
        """
        Publishes the pool LCD Output.
        """
        # Convert the pool_status object to a JSON string
        status_payload = text
        self.client.publish(self.LcdTextTopic, status_payload)
        #print(f"Published to {self.LcdTextTopic}: {status_payload}")       

    def start(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.mqtt_server, self.mqtt_port, 60)

        # Non-blocking loop start
        self.client.loop_start()

    def stop(self):
        # Stops the MQTT client loop and disconnects
        self.client.loop_stop()
        self.client.disconnect()


