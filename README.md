# UNS Automation System — Factory 1

Sistema de automação industrial baseado em **UNS (Unified Namespace)** usando MQTT como backbone de comunicação.

## Arquitetura

```
┌──────────────┐     MQTT      ┌───────────────────┐
│  Misturador  │──────────────▶│                   │
│  Envasadora  │──────────────▶│  Broker Mosquitto  │
│  Estoque     │──────────────▶│                   │
└──────────────┘               └────────┬──────────┘
                                        │
                     ┌──────────────────┴──────────────────┐
                     ▼                                       ▼
            ┌────────────────┐                    ┌──────────────────┐
            │    Consumidor  │──── SQLite ────────│   Dashboard      │
            │    Central     │    /data/uns.db    │   Streamlit      │
            │  (detecção +   │                    │  :8501           │
            │   automação)   │                    └──────────────────┘
            └────────────────┘
```

## Estrutura UNS (Tópicos MQTT)

```
factory1/
├── line1/
│   ├── mixer/
│   │   ├── temperature          (°C)
│   │   ├── vibration            (g)
│   │   ├── status               (running | stopped)
│   │   └── commands/shutdown    (automação)
│   └── filler/
│       ├── speed                (unidades/min)
│       ├── production_count     (unidades)
│       └── status               (running)
└── warehouse/
    ├── packaging_stock          (unidades)
    ├── raw_material_stock       (unidades)
    └── commands/restock_request (automação)
```

## Requisitos Funcionais Implementados

| RF | Descrição | Status |
|----|-----------|--------|
| RF1 | Publicação a cada 1 segundo | ✅ |
| RF2 | Persistência de eventos em SQLite | ✅ |
| RF3 | Detecção: temp > 80°C, vibração > 1.0 g, estoque < mínimo | ✅ |
| RF4 | Automação: desligamento por superaquecimento, reposição de estoque | ✅ |
| RF5 | Dashboard com estado, alertas e valores em tempo real | ✅ |

## Automações

| Condição | Ação |
|----------|------|
| Temperatura > 80°C | Publica `mixer/commands/shutdown`; mixer para por 30s |
| Embalagens < 100 | Publica `warehouse/commands/restock_request` (+500 unidades) |
| Matéria-prima < 50 | Publica `warehouse/commands/restock_request` (+200 unidades) |

Cooldown de 30 segundos evita spam de comandos automáticos.

## Como executar

```bash
docker compose up --build
```

- **Dashboard**: http://localhost:8501
- **MQTT Broker**: localhost:1883

## Monitorar logs

```bash
# Todos os serviços
docker compose logs -f

# Serviço específico
docker compose logs -f consumer
docker compose logs -f mixer
```

## Parar o sistema

```bash
docker compose down
```

Para apagar volumes (reset completo):
```bash
docker compose down -v
```
