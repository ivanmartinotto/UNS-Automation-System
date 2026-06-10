# UNS Automation System — Funcionamento Interno

## Visão Geral

O sistema implementa um **Unified Namespace (UNS)** industrial sobre MQTT. Seis contêineres Docker colaboram para simular uma fábrica, detectar anomalias automaticamente e exibir tudo em um dashboard em tempo real.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Docker Compose                             │
│                                                                     │
│  [mixer]──┐                                                         │
│  [filler]─┼──MQTT pub──▶ [mosquitto :1883] ──sub──▶ [consumer]     │
│  [warehouse]┘       ◀──MQTT pub──────────────────────               │
│                                              │                      │
│                                         SQLite /data/uns.db         │
│                                              │                      │
│                                         [dashboard :8501]           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Inicialização e Orquestração (Docker Compose)

O arquivo `docker-compose.yml` define seis serviços e a ordem de boot:

| Serviço | Imagem / Build | Porta | Dependência |
|---------|---------------|-------|-------------|
| `mosquitto` | `eclipse-mosquitto:2` | 1883 | — |
| `mixer` | `./simulators` | — | mosquitto healthy |
| `filler` | `./simulators` | — | mosquitto healthy |
| `warehouse` | `./simulators` | — | mosquitto healthy |
| `consumer` | `./consumer` | — | mosquitto healthy |
| `dashboard` | `./dashboard` | 8501 | mosquitto healthy + consumer started |

**Healthcheck do broker:** a cada 5 s o Compose publica uma mensagem de teste com `mosquitto_pub`. Somente após 10 tentativas bem-sucedidas os demais serviços recebem o sinal de saúde e sobem.

**Volume compartilhado `shared_data`:** montado em `/data` tanto no `consumer` quanto no `dashboard`. É o canal de persistência entre os dois — o consumer escreve, o dashboard lê.

---

## 2. Broker MQTT — Mosquitto

Arquivo: `mosquitto/config/mosquitto.conf`

```
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
```

- Aceita conexões sem autenticação na porta 1883.
- Habilita persistência em disco (volume `mosquitto_data`) para que mensagens QoS 1/2 sobrevivam a reinicializações.
- Todos os logs são enviados para stdout (visíveis via `docker compose logs -f mosquitto`).

O broker é o **hub central**: qualquer cliente que publique em um tópico tem a mensagem entregue a todos os assinantes daquele tópico — incluindo automações de volta para os simuladores.

---

## 3. Estrutura de Tópicos UNS (MQTT)

O namespace segue a hierarquia `empresa/planta/área/máquina/dado`:

```
factory1/
├── line1/
│   ├── mixer/
│   │   ├── temperature          ← float °C
│   │   ├── vibration            ← float g
│   │   ├── status               ← string "running" | "stopped"
│   │   └── commands/
│   │       └── shutdown         ← JSON {"reason":"overheating","temperature":...}
│   └── filler/
│       ├── speed                ← float unidades/min
│       ├── production_count     ← int acumulado
│       └── status               ← string "running"
└── warehouse/
    ├── packaging_stock          ← float unidades
    ├── raw_material_stock       ← float unidades
    └── commands/
        └── restock_request      ← JSON {"item":"packaging|raw_material","requested":N}
```

Tópicos sob `commands/` são usados exclusivamente para automações bidirecionais — o consumer publica, os simuladores escutam e reagem.

---

## 4. Simuladores

Todos compartilham a mesma imagem Docker (`./simulators`) e usam a biblioteca **paho-mqtt** com a API de callback versão 2. O padrão de boot é idêntico:

1. Lê `MQTT_BROKER` do ambiente (injetado pelo Compose como `mosquitto`).
2. Tenta conectar com retry em loop de 3 s até o broker responder.
3. Chama `client.loop_start()` para processar callbacks em background thread.
4. Entra no loop principal de publicação a cada **1 segundo**.

### 4.1 Mixer (`mixer_simulator.py`)

**O que simula:** misturador com risco de superaquecimento e vibração excessiva.

**Geração de dados:**
```python
temperature = round(random.gauss(68, 8), 2)   # média 68°C, std 8 → ~7% acima de 80°C
vibration   = round(max(0.0, random.gauss(0.5, 0.3)), 3)  # média 0.5g, std 0.3 → ~5% acima de 1.0g
```

**Publica a cada 1 s (quando `running = True`):**
- `factory1/line1/mixer/temperature` → valor float
- `factory1/line1/mixer/vibration` → valor float
- `factory1/line1/mixer/status` → `"running"`

**Quando `running = False`:** publica apenas `status = "stopped"` e aguarda.

**Escuta `factory1/line1/mixer/commands/#`:**
- `/shutdown` → seta `running = False` e agenda `restart_at = agora + 30s`
- `/restart` → seta `running = True` imediatamente

**Auto-restart:** a cada iteração do loop, verifica se `restart_at` passou; se sim, retoma operação sem precisar de comando externo.

### 4.2 Filler (`filler_simulator.py`)

**O que simula:** envasadora contínua, sem lógica de parada.

**Geração de dados:**
```python
speed = round(random.uniform(80, 150), 1)   # entre 80 e 150 unidades/min
production_count += int(speed / 60)          # acumula a cada segundo
```

**Publica a cada 1 s:**
- `factory1/line1/filler/speed`
- `factory1/line1/filler/production_count`
- `factory1/line1/filler/status` → `"running"` (sempre)

Não assina nenhum tópico de comando — é um produtor puro.

### 4.3 Warehouse (`warehouse_simulator.py`)

**O que simula:** estoque com consumo contínuo de embalagens e matéria-prima.

**Estado inicial:**
```python
packaging_stock    = 180.0   # mínimo: 100 → cruza em ~2 min
raw_material_stock =  80.0   # mínimo: 50  → cruza em ~2 min
```

**Consumo a cada 1 s:**
```python
packaging_stock    -= random.uniform(0.5, 2.0)
raw_material_stock -= random.uniform(0.2, 0.8)
```
Ambos são clampados em 0 para evitar valores negativos.

**Publica a cada 1 s:**
- `factory1/warehouse/packaging_stock`
- `factory1/warehouse/raw_material_stock`

**Escuta `factory1/warehouse/commands/#`:**
- `/restock_request` com payload JSON `{"item": "packaging|raw_material", "requested": N}` → adiciona `N` ao estoque correspondente.

---

## 5. Consumidor Central (`consumer/consumer.py`)

É o **cérebro** do sistema: assina todos os tópicos, detecta anomalias, persiste em banco e dispara automações.

### 5.1 Inicialização

```python
init_db()   # cria tabelas SQLite se não existirem
client.subscribe('factory1/#')   # assina tudo sob factory1/
```

O banco em `/data/uns.db` usa `PRAGMA journal_mode=WAL` para permitir leituras concorrentes pelo dashboard sem bloquear escritas.

**Tabelas criadas:**

```sql
CREATE TABLE current_state (
    topic      TEXT PRIMARY KEY,  -- ex: factory1/line1/mixer/temperature
    value      TEXT NOT NULL,     -- último valor recebido
    updated_at TEXT NOT NULL      -- ISO 8601 UTC
);

CREATE TABLE events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL,
    topic      TEXT NOT NULL,
    value      TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- "anomaly" | "automation"
    message    TEXT NOT NULL
);
```

### 5.2 Fluxo por mensagem recebida

```
MQTT on_message()
    │
    ├─ tópico contém "/commands/"? → IGNORAR (evita loop de feedback)
    │
    └─ handle_message()
           │
           ├─ update_state(topic, payload)    ← sempre, para todo tópico
           │
           ├─ tenta converter payload para float
           │   └─ falha? → retorna (strings como "running" não precisam de análise)
           │
           ├─ endswith('/temperature')?
           │   ├─ value > 80°C → log_event(anomaly)
           │   └─ can_trigger('mixer_shutdown')? → publica shutdown + log_event(automation)
           │
           ├─ endswith('/vibration')?
           │   └─ value > 1.0g → log_event(anomaly)  [sem automação associada]
           │
           ├─ endswith('/packaging_stock')?
           │   ├─ value < 100 → log_event(anomaly)
           │   └─ can_trigger('restock_packaging')? → publica restock +500 + log
           │
           └─ endswith('/raw_material_stock')?
               ├─ value < 50 → log_event(anomaly)
               └─ can_trigger('restock_raw_material')? → publica restock +200 + log
```

### 5.3 Controle de cooldown (anti-spam)

```python
AUTOMATION_COOLDOWN = 30  # segundos

def can_trigger(key: str) -> bool:
    now = time.time()
    if now - automation_last_triggered.get(key, 0) > AUTOMATION_COOLDOWN:
        automation_last_triggered[key] = now
        return True
    return False
```

Cada chave de automação (`mixer_shutdown`, `restock_packaging`, `restock_raw_material`) tem seu próprio timestamp. Um mesmo tipo de automação não é disparado mais de uma vez a cada 30 segundos, mesmo que chegem dezenas de leituras anômalas nesse intervalo.

### 5.4 Fluxo completo de automação — exemplo: superaquecimento

```
1. mixer publica  factory1/line1/mixer/temperature = 83.5
2. consumer recebe, chama handle_message()
3. update_state() → grava/atualiza linha na tabela current_state
4. 83.5 > 80.0  →  log_event(anomaly, "SUPERAQUECIMENTO: 83.5°C")
5. can_trigger('mixer_shutdown') == True (primeira vez)
6. consumer publica  factory1/line1/mixer/commands/shutdown
                     payload: {"reason": "overheating", "temperature": 83.5}
7. log_event(automation, "AUTO: Comando DESLIGAR enviado")
8. mixer recebe o shutdown → running = False, restart_at = agora + 30s
9. mixer passa a publicar apenas status="stopped"
10. após 30s, mixer reinicia automaticamente → running = True
```

---

## 6. Dashboard (`dashboard/app.py`)

Aplicação **Streamlit** que lê o SQLite e re-renderiza a cada 2 segundos.

### 6.1 Ciclo de refresh

```python
time.sleep(2)
st.rerun()   # força nova execução completa do script
```

Cada `st.rerun()` re-executa o script do zero, relendo o banco. Não há WebSocket ou push do servidor — é polling ativo pelo próprio processo.

### 6.2 Leitura de dados

`fetch_value(topic)` faz uma query pontual em `current_state`:
```sql
SELECT value FROM current_state WHERE topic = ?
```

`fetch_events(event_type, limit)` lê os eventos mais recentes:
```sql
SELECT timestamp, event_type, message FROM events
WHERE event_type = ?
ORDER BY id DESC LIMIT ?
```

### 6.3 Layout da interface

```
┌──────────────────────────────────────────────────────────┐
│  🏭 UNS Dashboard — Factory 1                            │
├──────────────┬──────────────┬───────────────────────────┤
│  Misturador  │  Envasadora  │  Estoque                  │
│  status      │  status      │  embalagens               │
│  temperatura │  velocidade  │  matéria-prima            │
│  vibração    │  produção    │                           │
├──────────────┴──────────────┴───────────────────────────┤
│  🚨 Alertas Recentes   │  📋 Log de Eventos             │
│  (anomaly, últimos 10) │  (todos, últimos 30)           │
├────────────────────────┴────────────────────────────────┤
│  📡 Estrutura de Tópicos UNS (expansível)               │
└─────────────────────────────────────────────────────────┘
```

**Indicadores visuais:** cada coluna exibe um badge 🔴/🟢 calculado em tempo de renderização comparando o valor lido com os thresholds — independente do que o consumer registrou.

---

## 7. Thresholds e Parâmetros Globais

| Parâmetro | Valor | Arquivo |
|-----------|-------|---------|
| Temperatura máxima | 80 °C | `consumer.py:TEMP_MAX` |
| Vibração máxima | 1.0 g | `consumer.py:VIBRATION_MAX` |
| Estoque mínimo — embalagens | 100 un | `consumer.py:PACKAGING_MIN` |
| Estoque mínimo — matéria-prima | 50 un | `consumer.py:RAW_MATERIAL_MIN` |
| Cooldown de automação | 30 s | `consumer.py:AUTOMATION_COOLDOWN` |
| Tempo parado do mixer | 30 s | `mixer_simulator.py:restart_at` |
| Reposição — embalagens | +500 un | `consumer.py:handle_message()` |
| Reposição — matéria-prima | +200 un | `consumer.py:handle_message()` |
| Intervalo de publicação | 1 s | todos os simuladores |
| Refresh do dashboard | 2 s | `dashboard/app.py` |

---

## 8. Fluxo de Dados End-to-End

```
t=0s  Docker Compose sobe mosquitto
t=5s  broker passa no healthcheck → mixer, filler, warehouse, consumer sobem
t=6s  consumer conecta e chama init_db() → cria uns.db
t=6s  consumer assina factory1/#
t=7s  simuladores conectam e começam a publicar a 1Hz
t=7s  dashboard sobe (depende de consumer started)

A cada 1s:
  mixer    → publica 3 tópicos (temperature, vibration, status)
  filler   → publica 3 tópicos (speed, production_count, status)
  warehouse→ publica 2 tópicos (packaging_stock, raw_material_stock)

  broker   → encaminha para consumer (assinou factory1/#)

  consumer → para cada mensagem:
              1. grava/atualiza current_state
              2. analisa valor numérico
              3. se anomalia: registra em events
              4. se automação cabível (cooldown ok): publica comando

A cada 2s:
  dashboard→ relê current_state e events do SQLite
           → re-renderiza todos os widgets
           → st.rerun()
```

---

## 9. Considerações de Concorrência

- **SQLite WAL mode:** permite que o dashboard leia enquanto o consumer escreve, sem deadlocks.
- **`timeout=10` no consumer / `timeout=5` no dashboard:** evita travamento indefinido em contenção de locks.
- **Uma conexão por operação no consumer:** `get_conn()` abre e fecha a conexão a cada `update_state` ou `log_event`. Isso garante que o WAL checkpoint ocorra normalmente sem conexões longas travando o arquivo.
- **`loop_start()` nos simuladores:** os callbacks MQTT (`on_message`) rodam em uma thread separada, enquanto o loop de publicação corre na thread principal. As variáveis globais `running` e `restart_at` são acessadas por ambas — em CPython isso é seguro para tipos primitivos devido ao GIL.
- **`loop_forever()` no consumer:** bloqueia a thread principal aguardando mensagens, com reconnect automático tratado externamente no `while True` do nível superior.
