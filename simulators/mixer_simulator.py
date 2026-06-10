"""
Simulador da Máquina A — Misturador
UNS Topics:
  factory1/line1/mixer/temperature
  factory1/line1/mixer/vibration
  factory1/line1/mixer/status
  factory1/line1/mixer/commands/#  (escuta)
"""
import paho.mqtt.client as mqtt
import time
import random
import os
import json

BROKER = os.environ.get('MQTT_BROKER', 'localhost')
BASE_TOPIC = 'factory1/line1/mixer'
PUBLISH_INTERVAL = 1

running = True
restart_at = None


def on_connect(client, userdata, flags, reason_code, properties=None):
    rc = reason_code if isinstance(reason_code, int) else reason_code.value
    if rc == 0:
        print('[mixer] Conectado ao broker MQTT')
        client.subscribe(f'{BASE_TOPIC}/commands/#')
    else:
        print(f'[mixer] Falha na conexão, rc={rc}')


def on_message(client, userdata, msg):
    global running, restart_at
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        payload = msg.payload.decode()

    if topic.endswith('/shutdown'):
        print(f'[mixer] Comando DESLIGAR recebido: {payload}')
        running = False
        restart_at = time.time() + 30
    elif topic.endswith('/restart'):
        print('[mixer] Comando LIGAR recebido')
        running = True
        restart_at = None


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='mixer-simulator')
client.on_connect = on_connect
client.on_message = on_message

while True:
    try:
        client.connect(BROKER, 1883, 60)
        break
    except Exception as e:
        print(f'[mixer] Aguardando broker: {e}')
        time.sleep(3)

client.loop_start()

while True:
    # Auto-restart depois de 30 segundos parado
    if restart_at and time.time() >= restart_at:
        running = True
        restart_at = None
        print('[mixer] Reiniciando automaticamente')

    if running:
        # Temperatura: média 68°C, std 8 → picos acima de 80°C ~7% do tempo
        temperature = round(random.gauss(68, 8), 2)
        # Vibração: média 0.5g, std 0.3 → picos acima de 1.0g ~5% do tempo
        vibration = round(max(0.0, random.gauss(0.5, 0.3)), 3)

        client.publish(f'{BASE_TOPIC}/temperature', temperature)
        client.publish(f'{BASE_TOPIC}/vibration', vibration)
        client.publish(f'{BASE_TOPIC}/status', 'running')
        print(f'[mixer] temp={temperature}°C  vib={vibration}g  status=running')
    else:
        client.publish(f'{BASE_TOPIC}/status', 'stopped')
        secs_left = max(0, int(restart_at - time.time())) if restart_at else '?'
        print(f'[mixer] status=stopped  (reinicia em {secs_left}s)')

    time.sleep(PUBLISH_INTERVAL)
