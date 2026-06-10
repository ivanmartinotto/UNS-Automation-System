"""
Simulador do Sistema de Estoque
UNS Topics:
  factory1/warehouse/packaging_stock
  factory1/warehouse/raw_material_stock
  factory1/warehouse/commands/#  (escuta pedidos de reposição)
"""
import paho.mqtt.client as mqtt
import time
import random
import os
import json

BROKER = os.environ.get('MQTT_BROKER', 'localhost')
BASE_TOPIC = 'factory1/warehouse'
PUBLISH_INTERVAL = 1

# Estoques iniciais escolhidos para cruzar os limites em ~2 minutos
packaging_stock = 180.0      # limite mínimo: 100
raw_material_stock = 80.0    # limite mínimo: 50


def on_connect(client, userdata, flags, reason_code, properties=None):
    rc = reason_code if isinstance(reason_code, int) else reason_code.value
    if rc == 0:
        print('[warehouse] Conectado ao broker MQTT')
        client.subscribe(f'{BASE_TOPIC}/commands/#')
    else:
        print(f'[warehouse] Falha na conexão, rc={rc}')


def on_message(client, userdata, msg):
    global packaging_stock, raw_material_stock
    try:
        payload = json.loads(msg.payload.decode())
        item = payload.get('item', '')
        quantity = float(payload.get('requested', 0))

        if item == 'packaging':
            packaging_stock += quantity
            print(f'[warehouse] REPOSIÇÃO embalagens +{quantity:.0f} → {packaging_stock:.0f}')
        elif item == 'raw_material':
            raw_material_stock += quantity
            print(f'[warehouse] REPOSIÇÃO matéria-prima +{quantity:.0f} → {raw_material_stock:.0f}')
    except Exception as e:
        print(f'[warehouse] Erro ao processar comando: {e}')


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='warehouse-simulator')
client.on_connect = on_connect
client.on_message = on_message

while True:
    try:
        client.connect(BROKER, 1883, 60)
        break
    except Exception as e:
        print(f'[warehouse] Aguardando broker: {e}')
        time.sleep(3)

client.loop_start()

while True:
    packaging_stock -= random.uniform(0.5, 2.0)
    raw_material_stock -= random.uniform(0.2, 0.8)

    packaging_stock = max(0.0, packaging_stock)
    raw_material_stock = max(0.0, raw_material_stock)

    client.publish(f'{BASE_TOPIC}/packaging_stock', round(packaging_stock, 1))
    client.publish(f'{BASE_TOPIC}/raw_material_stock', round(raw_material_stock, 1))
    print(f'[warehouse] embalagens={packaging_stock:.1f}  materia-prima={raw_material_stock:.1f}')

    time.sleep(PUBLISH_INTERVAL)
