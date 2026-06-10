"""
Dashboard UNS — Factory 1
Lê estado atual e eventos do SQLite gerado pelo consumidor central.
Auto-refresh a cada 2 segundos.
"""
import streamlit as st
import sqlite3
import pandas as pd
import time
import os

DB_PATH = os.environ.get('DB_PATH', '/data/uns.db')

st.set_page_config(
    page_title='UNS Dashboard — Factory 1',
    page_icon='🏭',
    layout='wide',
)

# ── helpers ──────────────────────────────────────────────────────────────────

def get_conn():
    return sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)


def fetch_value(topic: str) -> str | None:
    try:
        conn = get_conn()
        row = conn.execute(
            'SELECT value FROM current_state WHERE topic = ?', (topic,)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def fetch_events(event_type: str | None = None, limit: int = 30) -> pd.DataFrame:
    try:
        conn = get_conn()
        if event_type:
            df = pd.read_sql_query(
                'SELECT timestamp, event_type, message FROM events '
                'WHERE event_type = ? ORDER BY id DESC LIMIT ?',
                conn, params=(event_type, limit),
            )
        else:
            df = pd.read_sql_query(
                'SELECT timestamp, event_type, message FROM events '
                'ORDER BY id DESC LIMIT ?',
                conn, params=(limit,),
            )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame(columns=['timestamp', 'event_type', 'message'])


def fmt(val: str | None, unit: str = '', decimals: int = 1) -> str:
    if val is None:
        return '—'
    try:
        return f'{float(val):.{decimals}f}{unit}'
    except ValueError:
        return val


def alert_badge(condition: bool) -> str:
    return '🔴' if condition else '🟢'


# ── UI ────────────────────────────────────────────────────────────────────────

st.title('🏭 UNS Dashboard — Factory 1')
st.caption(f'Atualizado em: {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}  |  refresh a cada 2s')

db_exists = os.path.exists(DB_PATH)
if not db_exists:
    st.warning('Aguardando dados do consumidor central...')
    time.sleep(3)
    st.rerun()

st.divider()

# ── Linha de Produção ─────────────────────────────────────────────────────────
st.subheader('Linha de Produção')

col_mixer, col_filler, col_warehouse = st.columns(3)

with col_mixer:
    temp_val = fetch_value('factory1/line1/mixer/temperature')
    vib_val  = fetch_value('factory1/line1/mixer/vibration')
    status   = fetch_value('factory1/line1/mixer/status') or '—'

    temp_f = float(temp_val) if temp_val else 0.0
    vib_f  = float(vib_val)  if vib_val  else 0.0

    temp_alert = temp_f > 80
    vib_alert  = vib_f  > 1.0

    badge = '🔴' if (status == 'stopped' or temp_alert or vib_alert) else '🟢'
    st.markdown(f'#### {badge} Misturador (Mixer)')

    st.metric('Status',          status.upper())
    st.metric('Temperatura',     fmt(temp_val, ' °C'),
              delta='⚠ SUPERAQUECIMENTO' if temp_alert else 'Normal',
              delta_color='inverse' if temp_alert else 'off')
    st.metric('Vibração',        fmt(vib_val, ' g', 3),
              delta='⚠ VIBRAÇÃO ALTA' if vib_alert else 'Normal',
              delta_color='inverse' if vib_alert else 'off')

with col_filler:
    speed = fetch_value('factory1/line1/filler/speed')
    count = fetch_value('factory1/line1/filler/production_count')
    f_status = fetch_value('factory1/line1/filler/status') or '—'

    st.markdown('#### 🟢 Envasadora (Filler)')
    st.metric('Status',            f_status.upper())
    st.metric('Velocidade',        fmt(speed, ' u/min'))
    st.metric('Produção total',    fmt(count, ' unidades', 0))

with col_warehouse:
    pkg = fetch_value('factory1/warehouse/packaging_stock')
    raw = fetch_value('factory1/warehouse/raw_material_stock')

    pkg_f = float(pkg) if pkg else 0.0
    raw_f = float(raw) if raw else 0.0

    pkg_alert = pkg_f < 100
    raw_alert = raw_f < 50

    badge = '🔴' if (pkg_alert or raw_alert) else '🟢'
    st.markdown(f'#### {badge} Estoque (Warehouse)')

    st.metric('Embalagens',       fmt(pkg, ' un', 0),
              delta='⚠ ESTOQUE BAIXO' if pkg_alert else 'OK',
              delta_color='inverse' if pkg_alert else 'off')
    st.metric('Matéria-prima',    fmt(raw, ' un', 0),
              delta='⚠ ESTOQUE BAIXO' if raw_alert else 'OK',
              delta_color='inverse' if raw_alert else 'off')

st.divider()

# ── Alertas e Eventos ─────────────────────────────────────────────────────────
col_alerts, col_events = st.columns([1, 2])

with col_alerts:
    st.subheader('🚨 Alertas Recentes')
    alerts = fetch_events('anomaly', 10)
    if alerts.empty:
        st.success('Nenhum alerta ativo')
    else:
        for _, row in alerts.iterrows():
            ts = str(row['timestamp'])[:19].replace('T', ' ')
            st.error(f'**{ts}**  \n{row["message"]}')

with col_events:
    st.subheader('📋 Log de Eventos')
    events = fetch_events(limit=30)
    if events.empty:
        st.info('Sem eventos registrados ainda.')
    else:
        events['timestamp'] = events['timestamp'].str[:19].str.replace('T', ' ')
        events.columns = ['Timestamp', 'Tipo', 'Mensagem']
        st.dataframe(events, use_container_width=True, hide_index=True)

# ── Estrutura UNS ─────────────────────────────────────────────────────────────
with st.expander('📡 Estrutura de Tópicos UNS (MQTT)'):
    st.code('''
factory1/
├── line1/
│   ├── mixer/
│   │   ├── temperature
│   │   ├── vibration
│   │   ├── status
│   │   └── commands/
│   │       └── shutdown
│   └── filler/
│       ├── speed
│       ├── production_count
│       └── status
└── warehouse/
    ├── packaging_stock
    ├── raw_material_stock
    └── commands/
        └── restock_request
    ''', language='text')

# ── Auto-refresh ──────────────────────────────────────────────────────────────
time.sleep(2)
st.rerun()
