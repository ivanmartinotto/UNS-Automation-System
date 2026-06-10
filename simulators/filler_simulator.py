"""
Simulador da Máquina B — Envasadora
UNS Topics:
  factory1/line1/filler/speed
  factory1/line1/filler/production_count
  factory1/line1/filler/status
"""
import paho.mqtt.client as mqtt
import time
import random
import os

BROKER = os.environ.get('MQTT_BROKER', 'localhost')
BASE_TOPIC = 'factory1/line1/filler'
PUBLISH_INTERVAL = 1

production_count = 0


def on_connect(client, userdata, flags, reason_code, properties=None):
    rc = reason_code if isinstance(reason_code, int) else reason_code.value
    if rc == 0:
        print('[filler] Conectado ao broker MQTT')
    else:
        print(f'[filler] Falha na conexão, rc={rc}')


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='filler-simulator')
client.on_connect = on_connect

while True:
    try:
        client.connect(BROKER, 1883, 60)
        break
    except Exception as e:
        print(f'[filler] Aguardando broker: {e}')
        time.sleep(3)

client.loop_start()

while True:
    speed = round(random.uniform(80, 150), 1)
    production_count += int(speed / 60)

    client.publish(f'{BASE_TOPIC}/speed', speed)
    client.publish(f'{BASE_TOPIC}/production_count', production_count)
    client.publish(f'{BASE_TOPIC}/status', 'running')
    print(f'[filler] speed={speed} u/min  count={production_count}  status=running')

    time.sleep(PUBLISH_INTERVAL)
