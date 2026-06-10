"""
Consumidor Central UNS
- Assina factory1/# via MQTT
- Detecta anomalias (temperatura, vibração, estoque)
- Persiste eventos em SQLite
- Dispara automações (desligamento, reposição)
"""
import paho.mqtt.client as mqtt
import sqlite3
import json
import os
import time
from datetime import datetime, timezone

BROKER = os.environ.get('MQTT_BROKER', 'localhost')
DB_PATH = os.environ.get('DB_PATH', '/data/uns.db')

TEMP_MAX = 80.0
VIBRATION_MAX = 1.0
PACKAGING_MIN = 100
RAW_MATERIAL_MIN = 50

AUTOMATION_COOLDOWN = 30

automation_last_triggered: dict[str, float] = {}


# ── Banco de dados ──────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS current_state (
            topic      TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp  TEXT NOT NULL,
            topic      TEXT NOT NULL,
            value      TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message    TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()
    print(f'[consumer] DB inicializado em {DB_PATH}')


def update_state(topic: str, value: str) -> None:
    conn = get_conn()
    conn.execute(
        '''INSERT INTO current_state (topic, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(topic) DO UPDATE SET
             value      = excluded.value,
             updated_at = excluded.updated_at''',
        (topic, value, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def log_event(topic: str, value: str, event_type: str, message: str) -> None:
    conn = get_conn()
    conn.execute(
        'INSERT INTO events (timestamp, topic, value, event_type, message) VALUES (?, ?, ?, ?, ?)',
        (datetime.now(timezone.utc).isoformat(), topic, value, event_type, message),
    )
    conn.commit()
    conn.close()
    print(f'[consumer] [{event_type.upper()}] {message}')


# ── Controle de automação ───────────────────────────────────────────────────

def can_trigger(key: str) -> bool:
    now = time.time()
    if now - automation_last_triggered.get(key, 0) > AUTOMATION_COOLDOWN:
        automation_last_triggered[key] = now
        return True
    return False


# ── Detecção e automação ────────────────────────────────────────────────────

def handle_message(client: mqtt.Client, topic: str, payload: str) -> None:
    update_state(topic, payload)

    try:
        value = float(payload)
    except ValueError:
        return  # status strings não precisam de análise numérica

    if topic.endswith('/temperature'):
        if value > TEMP_MAX:
            msg = f'SUPERAQUECIMENTO: mixer temperatura {value:.1f}°C (limite: {TEMP_MAX}°C)'
            log_event(topic, payload, 'anomaly', msg)

            if can_trigger('mixer_shutdown'):
                cmd = json.dumps({'reason': 'overheating', 'temperature': value})
                client.publish('factory1/line1/mixer/commands/shutdown', cmd)
                log_event(topic, payload, 'automation',
                          f'AUTO: Comando DESLIGAR enviado ao mixer (temp={value:.1f}°C)')

    elif topic.endswith('/vibration'):
        if value > VIBRATION_MAX:
            msg = f'VIBRAÇÃO ALTA: mixer vibração {value:.3f} g (limite: {VIBRATION_MAX} g)'
            log_event(topic, payload, 'anomaly', msg)

    elif topic.endswith('/packaging_stock'):
        if value < PACKAGING_MIN:
            msg = f'ESTOQUE BAIXO: embalagens {value:.0f} unidades (mínimo: {PACKAGING_MIN})'
            log_event(topic, payload, 'anomaly', msg)

            if can_trigger('restock_packaging'):
                cmd = json.dumps({'item': 'packaging', 'requested': 500})
                client.publish('factory1/warehouse/commands/restock_request', cmd)
                log_event(topic, payload, 'automation',
                          f'AUTO: Pedido de reposição de embalagens (atual={value:.0f})')

    elif topic.endswith('/raw_material_stock'):
        if value < RAW_MATERIAL_MIN:
            msg = f'ESTOQUE BAIXO: matéria-prima {value:.0f} unidades (mínimo: {RAW_MATERIAL_MIN})'
            log_event(topic, payload, 'anomaly', msg)

            if can_trigger('restock_raw_material'):
                cmd = json.dumps({'item': 'raw_material', 'requested': 200})
                client.publish('factory1/warehouse/commands/restock_request', cmd)
                log_event(topic, payload, 'automation',
                          f'AUTO: Pedido de reposição de matéria-prima (atual={value:.0f})')


# ── MQTT callbacks ──────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties=None):
    rc = reason_code if isinstance(reason_code, int) else reason_code.value
    if rc == 0:
        print('[consumer] Conectado ao broker — assinando factory1/#')
        client.subscribe('factory1/#')
    else:
        print(f'[consumer] Falha na conexão, rc={rc}')


def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode(errors='replace')

    # Ignora tópicos de comando (evita loop de feedback)
    if '/commands/' in topic:
        return

    handle_message(client, topic, payload)


# ── Entrada ─────────────────────────────────────────────────────────────────

init_db()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='central-consumer')
client.on_connect = on_connect
client.on_message = on_message

while True:
    try:
        client.connect(BROKER, 1883, 60)
        print('[consumer] Iniciando loop...')
        client.loop_forever()
    except Exception as e:
        print(f'[consumer] Erro de conexão: {e} — tentando novamente em 5s')
        time.sleep(5)
