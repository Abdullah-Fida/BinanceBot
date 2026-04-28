import streamlit as st
import time
import json
import os
from binance.client import Client

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

st.set_page_config(page_title="Martingale Ultra Pro", layout="wide", page_icon="⚡", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap');
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
section.main > div { background-color: #0b0e11 !important; }
[data-testid="stSidebar"] > div:first-child {
    background-color: #161a1e !important;
    border-right: 1px solid #2b3139;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span { color: #848e9c !important; font-family: 'JetBrains Mono', monospace !important; }
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] .stSelectbox > div {
    background: #1e2329 !important; color: #eaecef !important; border: 1px solid #2b3139 !important;
}
[data-testid="stMain"] .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
.stButton > button {
    background: #f0b90b !important; color: #0b0e11 !important; border: none !important;
    font-weight: 700 !important; font-family: 'JetBrains Mono', monospace !important;
    border-radius: 6px !important; font-size: 13px !important; letter-spacing: 1px !important;
}
.stButton > button:hover { background: #d4a009 !important; }
#MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 💾  PERSISTENCE
# =========================================================
STATS_FILE = "bot_stats.json"
CREDS_FILE = "bot_creds.json"

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tp_counts": {}, "profits": {}}

def save_stats(tp_counts, profits):
    try:
        with open(STATS_FILE, "w") as f:
            json.dump({"tp_counts": tp_counts, "profits": profits}, f)
    except Exception:
        pass

def load_creds():
    # 1. Check Streamlit Secrets first (for cloud hosting)
    try:
        if "BINANCE_API_KEY" in st.secrets and "BINANCE_API_SECRET" in st.secrets:
            return {
                "api_key": st.secrets["BINANCE_API_KEY"],
                "api_secret": st.secrets["BINANCE_API_SECRET"]
            }
    except Exception:
        pass

    # 2. Fallback to local JSON file
    if os.path.exists(CREDS_FILE):
        try:
            with open(CREDS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"api_key": "", "api_secret": ""}

def save_creds(key, secret):
    try:
        with open(CREDS_FILE, "w") as f:
            json.dump({"api_key": key, "api_secret": secret}, f)
    except Exception:
        pass

# =========================================================
# 📦  SESSION STATE INIT
# =========================================================
_creds = load_creds()
_stats = load_stats()

for _k, _v in [
    ("running",      False),
    ("logs",         [{"t": time.strftime("%H:%M:%S"), "msg": "System Online", "type": "info"}]),
    ("positions",    {}),
    ("tp_counts",    _stats.get("tp_counts", {})),
    ("profits",      _stats.get("profits", {})),
    ("symbol_info",  {}),
    ("saved_key",    _creds.get("api_key", "")),
    ("saved_secret", _creds.get("api_secret", "")),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

def add_log(msg, typ="info"):
    st.session_state.logs.append({"t": time.strftime("%H:%M:%S"), "msg": msg, "type": typ})
    if len(st.session_state.logs) > 80:
        st.session_state.logs = st.session_state.logs[-80:]

# =========================================================
# 🔧  SIDEBAR
# =========================================================
st.sidebar.markdown("## ⚡ BOT CONTROL")

API_KEY_INPUT    = st.sidebar.text_input("API Key",    value=st.session_state.saved_key,    type="password")
API_SECRET_INPUT = st.sidebar.text_input("API Secret", value=st.session_state.saved_secret, type="password")

# Prioritize Streamlit Secrets over the text boxes
try:
    if "BINANCE_API_KEY" in st.secrets and "BINANCE_API_SECRET" in st.secrets:
        API_KEY = st.secrets["BINANCE_API_KEY"]
        API_SECRET = st.secrets["BINANCE_API_SECRET"]
    else:
        API_KEY = API_KEY_INPUT
        API_SECRET = API_SECRET_INPUT
except Exception:
    API_KEY = API_KEY_INPUT
    API_SECRET = API_SECRET_INPUT

# Auto-save credentials if manually typed
if API_KEY_INPUT and API_SECRET_INPUT:
    if API_KEY_INPUT != st.session_state.saved_key or API_SECRET_INPUT != st.session_state.saved_secret:
        save_creds(API_KEY_INPUT, API_SECRET_INPUT)
        st.session_state.saved_key    = API_KEY_INPUT
        st.session_state.saved_secret = API_SECRET_INPUT

ALL_PAIRS      = ["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
selected_pairs = st.sidebar.multiselect("Trading Pairs", ALL_PAIRS, default=["SOLUSDT"])

st.sidebar.markdown("---")
START_USDT       = st.sidebar.number_input("Initial Entry ($)",        value=50,  min_value=10, step=10)
TP_PERCENT       = st.sidebar.slider("Take Profit %",                  0.1, 5.0, 1.0, 0.1) / 100
MARTINGALE_DROP  = st.sidebar.slider("Re-entry Drop %",                0.1, 5.0, 1.5, 0.1) / 100
MARTINGALE_MULT  = st.sidebar.slider("Size Multiplier",                1.1, 3.0, 2.0, 0.1)
MAX_LEVELS       = st.sidebar.slider("Max Martingale Levels",          2,   10,  5)
REFRESH_INTERVAL = st.sidebar.slider("Refresh Interval (sec)",         3,   30,  5)
DIRECTION        = st.sidebar.selectbox("Direction", ["LONG", "SHORT", "BOTH"])
STOP_LOSS_PCT    = st.sidebar.slider("Stop Loss %",                       1.0, 25.0, 10.0, 0.5) / 100

st.sidebar.markdown("---")
st.sidebar.markdown("## 🛡️ SAFETY")
if st.sidebar.button("🔄 Reconnect API"):
    st.session_state.pop("client", None)
    st.session_state.symbol_info = {}
    st.rerun()

if st.sidebar.button("🔁 Sync Exchange Positions"):
    st.session_state["_do_sync"] = True
    st.rerun()

if st.sidebar.button("🚨 EMERGENCY CLOSE ALL"):
    st.session_state["_do_close_all"] = True
    st.rerun()

# =========================================================
# 🔌  BINANCE CLIENT
# =========================================================
def build_client():
    if not API_KEY or not API_SECRET:
        add_log("No API credentials found — check Secrets or sidebar", "error")
        return None
    try:
        # Log where credentials came from (masked)
        masked_key = API_KEY[:4] + "..." + API_KEY[-4:] if len(API_KEY) > 8 else "***"
        try:
            source = "Streamlit Secrets" if ("BINANCE_API_KEY" in st.secrets) else "Sidebar Input"
        except Exception:
            source = "Sidebar Input"
        add_log(f"Connecting via {source} (key: {masked_key})", "info")
        
        c = Client(API_KEY, API_SECRET, testnet=True, requests_params={"timeout": 10})
        c.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
        
        # Test the connection
        c.futures_ping()
        add_log("API Connected ✓", "open")
        return c
    except Exception as e:
        add_log(f"API Connection Failed: {e}", "error")
        return None

def ensure_hedge_mode(c):
    """Enable hedge mode so LONG and SHORT can run simultaneously."""
    if "hedge_mode_set" in st.session_state:
        return
    try:
        pos_mode = c.futures_get_position_mode()
        if not pos_mode.get("dualSidePosition", False):
            c.futures_change_position_mode(dualSidePosition=True)
            add_log("Hedge mode ENABLED ✓", "open")
        else:
            add_log("Hedge mode already ON ✓", "info")
        st.session_state.hedge_mode_set = True
    except Exception as e:
        add_log(f"Hedge mode error: {e}", "error")

if "client" not in st.session_state:
    st.session_state.client = build_client()
if st.session_state.client is None and API_KEY and API_SECRET:
    st.session_state.client = build_client()

client = st.session_state.client

# Auto-enable hedge mode on connect
if client and "hedge_mode_set" not in st.session_state:
    ensure_hedge_mode(client)

# =========================================================
# 📡  HELPERS
# =========================================================
def get_wallet_balance():
    if not client: return 0.0
    try:
        for b in client.futures_account_balance():
            if b["asset"] == "USDT":
                return float(b["balance"])
    except Exception:
        pass
    return 0.0

def get_price(symbol):
    if not client: return 0.0
    try:
        return float(client.futures_symbol_ticker(symbol=symbol)["price"])
    except Exception:
        return 0.0

def get_qty_step(symbol):
    if symbol in st.session_state.symbol_info:
        return st.session_state.symbol_info[symbol]
    try:
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step = float(f["stepSize"])
                        st.session_state.symbol_info[symbol] = step
                        add_log(f"Precision [{symbol}] step={step}", "info")
                        return step
    except Exception as e:
        add_log(f"Precision error [{symbol}]: {e}", "error")
    return 1.0

def round_qty(symbol, qty):
    step = get_qty_step(symbol)
    if step <= 0:
        step = 1.0
    qty = (qty // step) * step
    step_str = f"{step:.10f}".rstrip("0")
    decimals = len(step_str.split(".")[-1]) if "." in step_str else 0
    return round(qty, decimals)

def place_order(symbol, side, quantity, position_side):
    try:
        client.futures_create_order(
            symbol=symbol, side=side, type="MARKET",
            quantity=quantity, positionSide=position_side
        )
        return True
    except Exception as e:
        add_log(f"Order Error [{symbol}]: {e}", "error")
        return False

def pkey(sym, side):
    return f"{sym}_{side}"

def sync_positions_with_exchange():
    """Detect exchange positions not tracked internally."""
    if not client:
        add_log("No client — cannot sync", "error")
        return
    try:
        ex_positions = client.futures_position_information()
        for pos in ex_positions:
            amt = float(pos.get("positionAmt", 0))
            if amt == 0:
                continue
            symbol = pos["symbol"]
            side = "long" if amt > 0 else "short"
            tracked = st.session_state.positions.get(symbol, {}).get(side, {}).get("levels", [])
            if not tracked:
                entry_price = float(pos.get("entryPrice", 0))
                add_log(f"UNTRACKED {side.upper()} {symbol} qty={abs(amt)} entry=${entry_price:.4f}", "warn")
            else:
                add_log(f"Synced OK: {side.upper()} {symbol}", "info")
    except Exception as e:
        add_log(f"Sync error: {e}", "error")

def close_all_positions():
    """Emergency: close every tracked position immediately."""
    if not client:
        add_log("No client — cannot close", "error")
        return
    closed = 0
    for sym, sides in list(st.session_state.positions.items()):
        for side in ["long", "short"]:
            levels = sides.get(side, {}).get("levels", [])
            if not levels:
                continue
            total_qty = sum(l["qty"] for l in levels)
            if total_qty <= 0:
                continue
            close_side = "SELL" if side == "long" else "BUY"
            if place_order(sym, close_side, total_qty, side.upper()):
                avg_p = sum(l["price"] * l["qty"] for l in levels) / total_qty
                cp = get_price(sym)
                pnl = (cp - avg_p) * total_qty if side == "long" else (avg_p - cp) * total_qty
                k = pkey(sym, side)
                st.session_state.profits[k] = st.session_state.profits.get(k, 0.0) + pnl
                save_stats(st.session_state.tp_counts, st.session_state.profits)
                st.session_state.positions[sym][side] = {"levels": [], "last_entry_price": None}
                add_log(f"EMERGENCY CLOSE {side.upper()} {sym} | PnL ${pnl:.2f}", "error")
                closed += 1
    add_log(f"Closed {closed} position(s)", "warn")

# Handle sidebar button actions
if st.session_state.pop("_do_sync", False):
    sync_positions_with_exchange()
if st.session_state.pop("_do_close_all", False):
    close_all_positions()

# =========================================================
# 🔄  MARTINGALE ENGINE
# =========================================================
def get_next_usdt(levels):
    if not levels:
        return START_USDT
    return START_USDT * (MARTINGALE_MULT ** len(levels))

def open_initial(symbol, side, price):
    qty = round_qty(symbol, START_USDT / price)
    if qty <= 0:
        add_log(f"Qty too small [{symbol}] — raise Initial Entry $", "warn")
        return
    order_side = "BUY" if side == "long" else "SELL"
    if place_order(symbol, order_side, qty, side.upper()):
        if symbol not in st.session_state.positions:
            st.session_state.positions[symbol] = {}
        st.session_state.positions[symbol][side] = {
            "levels": [{"price": price, "qty": qty, "usdt": START_USDT}],
            "last_entry_price": price,
        }
        add_log(f"L1 OPEN {side.upper()} {symbol} @ {price:.4f} | ${START_USDT:.0f} qty={qty}", "open")

def open_martingale(symbol, side, price, current_levels):
    level_num = len(current_levels) + 1
    usdt_size = get_next_usdt(current_levels)
    qty       = round_qty(symbol, usdt_size / price)
    if qty <= 0:
        add_log(f"Qty too small L{level_num} [{symbol}] — skipping", "warn")
        return
    order_side = "BUY" if side == "long" else "SELL"
    if place_order(symbol, order_side, qty, side.upper()):
        current_levels.append({"price": price, "qty": qty, "usdt": usdt_size})
        st.session_state.positions[symbol][side]["last_entry_price"] = price
        add_log(f"L{level_num} DCA {side.upper()} {symbol} @ {price:.4f} | ${usdt_size:.0f} qty={qty}", "dca")

def close_position(symbol, side, levels, avg_price, curr_price):
    total_qty  = sum(l["qty"] for l in levels)
    close_side = "SELL" if side == "long" else "BUY"
    if place_order(symbol, close_side, total_qty, side.upper()):
        pnl = (curr_price - avg_price) * total_qty if side == "long" \
              else (avg_price - curr_price) * total_qty
        k = pkey(symbol, side)
        st.session_state.tp_counts[k] = st.session_state.tp_counts.get(k, 0) + 1
        st.session_state.profits[k]   = st.session_state.profits.get(k, 0.0) + pnl
        save_stats(st.session_state.tp_counts, st.session_state.profits)
        lvl_count = len(levels)
        st.session_state.positions[symbol][side] = {"levels": [], "last_entry_price": None}
        add_log(f"TP HIT {side.upper()} {symbol} L{lvl_count} | +${pnl:.2f}", "tp")

def run_cycle():
    if not client:
        add_log("No API client — enter credentials in sidebar", "error")
        return

    # FIX: DIRECTION controls which sides to trade
    sides_map = {"LONG": ["long"], "SHORT": ["short"], "BOTH": ["long", "short"]}
    sides_to_run = sides_map[DIRECTION]

    for symbol in selected_pairs:
        curr_price = get_price(symbol)
        if curr_price == 0:
            continue

        if symbol not in st.session_state.positions:
            st.session_state.positions[symbol] = {}

        for side in sides_to_run:
            # FIX: always ensure the side key exists before accessing
            if side not in st.session_state.positions[symbol]:
                st.session_state.positions[symbol][side] = {"levels": [], "last_entry_price": None}

            pos    = st.session_state.positions[symbol][side]
            levels = pos["levels"]

            if not levels:
                open_initial(symbol, side, curr_price)
                continue

            total_qty = sum(l["qty"] for l in levels)
            if total_qty == 0:
                continue

            avg_price        = sum(l["price"] * l["qty"] for l in levels) / total_qty
            last_entry_price = pos.get("last_entry_price") or avg_price

            tp_price = avg_price * (1 + TP_PERCENT) if side == "long" \
                       else avg_price * (1 - TP_PERCENT)
            tp_hit   = (side == "long"  and curr_price >= tp_price) or \
                       (side == "short" and curr_price <= tp_price)

            if tp_hit:
                close_position(symbol, side, levels, avg_price, curr_price)
                continue

            # --- STOP-LOSS CHECK ---
            if side == "long":
                loss_pct = (avg_price - curr_price) / avg_price
            else:
                loss_pct = (curr_price - avg_price) / avg_price
            if loss_pct >= STOP_LOSS_PCT:
                close_side = "SELL" if side == "long" else "BUY"
                if place_order(symbol, close_side, total_qty, side.upper()):
                    pnl = (curr_price - avg_price) * total_qty if side == "long" \
                          else (avg_price - curr_price) * total_qty
                    k = pkey(symbol, side)
                    st.session_state.profits[k] = st.session_state.profits.get(k, 0.0) + pnl
                    save_stats(st.session_state.tp_counts, st.session_state.profits)
                    st.session_state.positions[symbol][side] = {"levels": [], "last_entry_price": None}
                    add_log(f"\U0001f6d1 STOP LOSS {side.upper()} {symbol} L{len(levels)} | ${pnl:.2f} (-{loss_pct*100:.1f}%)", "error")
                continue

            if len(levels) < MAX_LEVELS:
                drop_hit = (side == "long"  and curr_price <= last_entry_price * (1 - MARTINGALE_DROP)) or \
                           (side == "short" and curr_price >= last_entry_price * (1 + MARTINGALE_DROP))
                if drop_hit:
                    open_martingale(symbol, side, curr_price, levels)

# =========================================================
# 🎨  UI HELPERS
# =========================================================
def metric_card(label, value, color="#eaecef"):
    return f"""
    <div style="background:#161a1e;border:1px solid #2b3139;border-radius:10px;
                padding:20px 24px;flex:1;min-width:150px;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#848e9c;
                    text-transform:uppercase;letter-spacing:1.2px;margin-bottom:12px;">{label}</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;color:{color};">{value}</div>
    </div>"""

def render_metrics(bal, realized, unrealized, tp_hits, exposure):
    unreal_color = "#0ecb81" if unrealized >= 0 else "#f6465d"
    real_color   = "#0ecb81" if realized  >= 0 else "#f6465d"
    sign         = "+" if unrealized >= 0 else ""
    st.markdown(f"""
    <div style="display:flex;gap:14px;margin-bottom:20px;flex-wrap:wrap;">
        {metric_card("💳 Wallet Balance",  f"${bal:.2f}")}
        {metric_card("✅ Realized P&L",    f"${realized:.2f}",              real_color)}
        {metric_card("📉 Unrealized P&L",  f"{sign}${abs(unrealized):.2f}", unreal_color)}
        {metric_card("🎯 Total TP Hits",   str(tp_hits),                    "#f0b90b")}
        {metric_card("💰 Total Exposure",  f"${exposure:.0f}",              "#ff9800")}
    </div>
    """, unsafe_allow_html=True)

# Styled log with colour-coded event types
LOG_STYLES = {
    "info":  ("#525c6a", "#0d1117", "·"),
    "open":  ("#0ecb81", "#061510", "▲"),
    "dca":   ("#f0b90b", "#130f02", "◆"),
    "tp":    ("#0ecb81", "#061510", "✅"),
    "error": ("#f6465d", "#130209", "✖"),
    "warn":  ("#ff9800", "#130a02", "⚠"),
}

def render_log(logs):
    rows_html = ""
    for entry in reversed(logs[-25:]):
        typ              = entry.get("type", "info")
        col, bg, icon    = LOG_STYLES.get(typ, LOG_STYLES["info"])
        rows_html += f"""
        <div style="display:flex;align-items:center;gap:10px;padding:6px 14px;
                    background:{bg};border-left:3px solid {col};margin-bottom:2px;">
            <span style="color:{col};font-size:12px;min-width:18px;text-align:center;">{icon}</span>
            <span style="color:#3a4255;font-size:11px;white-space:nowrap;min-width:60px;">{entry["t"]}</span>
            <span style="color:{col};font-size:12px;font-weight:600;">{entry["msg"]}</span>
        </div>"""

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #2b3139;border-radius:10px;overflow:hidden;
                font-family:'JetBrains Mono',monospace;">
        <div style="padding:8px 14px;background:#161a1e;border-bottom:1px solid #2b3139;
                    font-size:10px;color:#848e9c;letter-spacing:1.5px;text-transform:uppercase;">
            📋 Activity Log
        </div>
        <div style="max-height:230px;overflow-y:auto;padding:4px 0;">{rows_html}</div>
    </div>
    """, unsafe_allow_html=True)

def render_table(rows):
    if not rows:
        st.markdown("""
        <div style="background:#161a1e;border:1px solid #2b3139;border-radius:10px;
                    padding:50px;text-align:center;color:#848e9c;
                    font-family:'JetBrains Mono',monospace;font-size:14px;">
            ● No active positions — start the bot to begin trading
        </div>""", unsafe_allow_html=True)
        return

    headers = ["SYMBOL", "SIDE", "LEVEL", "SIZE", "AVG ENTRY", "CURRENT",
               "TARGET TP", "EXP. PROFIT", "NEXT DCA @", "NEXT DCA $",
               "RUNNING PNL", "TOTAL PROFIT", "HITS"]

    header_html = "".join(
        f"""<th style="background:#1a1f26;color:#5a6478;font-family:'JetBrains Mono',monospace;
                font-size:11px;text-transform:uppercase;letter-spacing:0.8px;
                padding:14px 18px;border-bottom:2px solid #2b3139;
                white-space:nowrap;text-align:center;">{h}</th>"""
        for h in headers
    )

    rows_html = ""
    for i, r in enumerate(rows):
        side_color  = "#0ecb81" if r["SIDE"] == "LONG" else "#f6465d"
        pnl_color   = "#0ecb81" if r["RUNNING PNL"] >= 0 else "#f6465d"
        pnl_sign    = "+" if r["RUNNING PNL"] >= 0 else ""
        level_num   = int(r["LEVEL"][1:])
        level_color = ["#848e9c","#eaecef","#f0b90b","#ff9800","#f6465d",
                       "#c62828","#c62828","#c62828","#c62828","#c62828","#c62828"][min(level_num, 10)]
        row_bg      = "#0f1318" if i % 2 == 0 else "#111620"

        cells = [
            (r["SYMBOL"],                                "#eaecef", "700"),
            (r["SIDE"],                                  side_color,"700"),
            (r["LEVEL"],                                 level_color,"700"),
            (r["SIZE"],                                  "#eaecef", "400"),
            (f"${r['AVG ENTRY']:.4f}",                   "#eaecef", "400"),
            (f"${r['CURRENT']:.4f}",                     "#f0b90b", "600"),
            (f"${r['TARGET TP']:.4f}",                   "#0ecb81", "600"),
            (f"+${r['EXP. PROFIT']:.2f}",                "#0ecb81", "700"),  # FIX: Expected profit
            (f"${r['NEXT DCA @']:.4f}",                  "#f6465d", "400"),
            (f"${r['NEXT DCA $']:.0f}",                  "#848e9c", "400"),
            (f"{pnl_sign}${abs(r['RUNNING PNL']):.2f}",  pnl_color, "700"),
            (f"${r['TOTAL PROFIT']:.2f}",                "#0ecb81", "400"),
            (str(r["HITS"]),                             "#f0b90b", "700"),
        ]

        cells_html = "".join(
            f"""<td style="padding:16px 18px;text-align:center;border-bottom:1px solid #1a2030;
                    font-family:'JetBrains Mono',monospace;font-size:14px;
                    color:{color};font-weight:{fw};">{val}</td>"""
            for val, color, fw in cells
        )
        rows_html += f'<tr style="background:{row_bg};">{cells_html}</tr>'

    st.markdown(f"""
    <div style="background:#0d1117;border:1px solid #2b3139;border-radius:10px;
                overflow:hidden;margin-top:10px;">
        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_level_breakdown(positions):
    has_any = any(
        pos.get(side, {}).get("levels")
        for sym, pos in positions.items()
        for side in ["long", "short"]
    )
    if not has_any:
        return

    st.markdown("""
    <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#848e9c;
                text-transform:uppercase;letter-spacing:1.5px;margin:28px 0 10px 0;">
        🔢 Level Breakdown
    </div>""", unsafe_allow_html=True)

    for sym, pos in positions.items():
        cp = get_price(sym)
        for side in ["long", "short"]:
            levels = pos.get(side, {}).get("levels", [])
            if not levels:
                continue
            side_color = "#0ecb81" if side == "long" else "#f6465d"
            rows_html  = ""
            for i, lvl in enumerate(levels, 1):
                pnl = (cp - lvl["price"]) * lvl["qty"] if side == "long" \
                      else (lvl["price"] - cp) * lvl["qty"]
                pnl_color = "#0ecb81" if pnl >= 0 else "#f6465d"
                sign      = "+" if pnl >= 0 else ""
                row_bg    = "#0f1318" if i % 2 == 0 else "#111620"
                rows_html += f"""
                <tr style="background:{row_bg};">
                    <td style="padding:12px 18px;color:#848e9c;font-weight:700;font-size:14px;">L{i}</td>
                    <td style="padding:12px 18px;color:#eaecef;font-size:14px;">${lvl["price"]:.4f}</td>
                    <td style="padding:12px 18px;color:#eaecef;font-size:14px;">{lvl["qty"]}</td>
                    <td style="padding:12px 18px;color:#eaecef;font-size:14px;">${lvl["usdt"]:.0f}</td>
                    <td style="padding:12px 18px;color:{pnl_color};font-weight:700;font-size:14px;">{sign}${abs(pnl):.2f}</td>
                </tr>"""

            st.markdown(f"""
            <div style="background:#0d1117;border:1px solid #2b3139;border-radius:10px;
                        overflow:hidden;margin-bottom:14px;">
                <div style="padding:12px 18px;border-bottom:1px solid #2b3139;background:#161a1e;
                            font-family:'JetBrains Mono',monospace;font-size:13px;">
                    <span style="color:{side_color};font-weight:700;">{side.upper()}</span>
                    <span style="color:#848e9c;"> · {sym} · {len(levels)} active levels</span>
                </div>
                <div style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace;">
                        <thead>
                            <tr style="background:#1a1f26;">
                                <th style="padding:11px 18px;color:#5a6478;font-size:11px;text-align:left;">LVL</th>
                                <th style="padding:11px 18px;color:#5a6478;font-size:11px;text-align:left;">ENTRY PRICE</th>
                                <th style="padding:11px 18px;color:#5a6478;font-size:11px;text-align:left;">QTY</th>
                                <th style="padding:11px 18px;color:#5a6478;font-size:11px;text-align:left;">USDT</th>
                                <th style="padding:11px 18px;color:#5a6478;font-size:11px;text-align:left;">PNL</th>
                            </tr>
                        </thead>
                        <tbody>{rows_html}</tbody>
                    </table>
                </div>
            </div>
            """, unsafe_allow_html=True)

# =========================================================
# 🖥️  DASHBOARD
# =========================================================
st.markdown("""
<div style="text-align:center;padding:10px 0 4px 0;">
    <div style="font-family:'JetBrains Mono',monospace;font-size:28px;font-weight:700;
                color:#f0b90b;letter-spacing:4px;">⚡ MARTINGALE ULTRA PRO</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#525c6a;
                letter-spacing:2px;margin-top:6px;">
        AUTOMATED FUTURES SCALPING BOT &nbsp;·&nbsp; TESTNET
    </div>
</div>
<hr style="border:none;border-top:1px solid #2b3139;margin:18px 0;">
""", unsafe_allow_html=True)

bal        = get_wallet_balance()
realized   = sum(st.session_state.profits.values())
unrealized = 0.0
exposure   = 0.0
for sym, sides in st.session_state.positions.items():
    cp = get_price(sym)
    for side, data in sides.items():
        for lvl in data.get("levels", []):
            unrealized += (cp - lvl["price"]) * lvl["qty"] if side == "long" \
                     else (lvl["price"] - cp) * lvl["qty"]
            exposure += lvl.get("usdt", 0)

render_metrics(bal, realized, unrealized, sum(st.session_state.tp_counts.values()), exposure)

ctrl_col, log_col = st.columns([1, 2])

with ctrl_col:
    if not st.session_state.running:
        if st.button("▶  START BOT", use_container_width=True, type="primary"):
            if not API_KEY or not API_SECRET:
                st.warning("Enter API credentials in the sidebar first.")
            else:
                st.session_state.running = True
                add_log("Bot started", "info")
                st.rerun()
    else:
        st.markdown("""<style>
        div[data-testid="stButton"]:has(button#stop_btn) > button {
            background: #1a0a0a !important; color: #f6465d !important;
            border: 1px solid #f6465d !important;
        }
        </style>""", unsafe_allow_html=True)
        if st.button("■  STOP BOT", use_container_width=True, key="stop_btn"):
            st.session_state.running = False
            add_log("Bot stopped", "warn")
            st.rerun()

    status_color = "#0ecb81" if st.session_state.running else "#f6465d"
    status_label = "● LIVE" if st.session_state.running else "● IDLE"
    st.markdown(
        f'<div style="text-align:center;margin-top:12px;font-family:JetBrains Mono,monospace;'
        f'font-size:13px;letter-spacing:2px;color:{status_color};">{status_label}</div>',
        unsafe_allow_html=True,
    )

with log_col:
    render_log(st.session_state.logs)

st.markdown("""
<div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#848e9c;
            text-transform:uppercase;letter-spacing:1.5px;margin:24px 0 6px 0;">
    📊 Active Market Monitor
</div>""", unsafe_allow_html=True)

rows = []
for sym, sides in st.session_state.positions.items():
    cp = get_price(sym)
    for side in ["long", "short"]:
        data   = sides.get(side, {})
        levels = data.get("levels", [])
        if not levels:
            continue
        total_qty = sum(l["qty"] for l in levels)
        if total_qty == 0:
            continue

        avg_p            = sum(l["price"] * l["qty"] for l in levels) / total_qty
        last_entry_price = data.get("last_entry_price") or avg_p
        tp               = avg_p * (1 + TP_PERCENT) if side == "long" else avg_p * (1 - TP_PERCENT)
        pnl              = (cp - avg_p) * total_qty if side == "long" else (avg_p - cp) * total_qty
        exp_profit       = abs(tp - avg_p) * total_qty   # FIX: expected profit at TP
        next_dca         = last_entry_price * (1 - MARTINGALE_DROP) if side == "long" \
                           else last_entry_price * (1 + MARTINGALE_DROP)
        next_usdt        = get_next_usdt(levels) if len(levels) < MAX_LEVELS else 0
        k                = pkey(sym, side)

        rows.append({
            "SYMBOL":       sym,
            "SIDE":         side.upper(),
            "LEVEL":        f"L{len(levels)}",
            "SIZE":         f"{total_qty}",
            "AVG ENTRY":    avg_p,
            "CURRENT":      cp,
            "TARGET TP":    tp,
            "EXP. PROFIT":  exp_profit,
            "NEXT DCA @":   next_dca,
            "NEXT DCA $":   next_usdt,
            "RUNNING PNL":  pnl,
            "TOTAL PROFIT": st.session_state.profits.get(k, 0.0),
            "HITS":         st.session_state.tp_counts.get(k, 0),
        })

render_table(rows)
render_level_breakdown(st.session_state.positions)

# =========================================================
# 🔁  NON-BLOCKING REFRESH
# =========================================================
if st.session_state.running:
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=REFRESH_INTERVAL * 1000, limit=None, key="bot_refresh")
    run_cycle()
    if not HAS_AUTOREFRESH:
        time.sleep(REFRESH_INTERVAL)
        st.rerun()