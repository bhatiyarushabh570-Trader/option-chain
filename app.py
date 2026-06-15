import streamlit as st
import pandas as pd
from fyers_apiv3 import fyersModel
import time

st.set_page_config(layout="wide", page_title="Live Option Chain Matrix")

# --- 1. WEB-BASED AUTHENTICATION PROMPT ---
st.sidebar.header("🔑 FYERS API Connectivity")
app_id = st.sidebar.text_input("FYERS App ID", type="password", help="Enter your App ID from the FYERS developer dashboard")
access_token = st.sidebar.text_input("Access Token / Auth Code", type="password", help="Paste your active daily access token here")

# --- 2. AUTOMATIC LIVE REFRESH CONTROLS ---
st.sidebar.write("---")
st.sidebar.header("🔄 Live Refresh Engine")
auto_refresh = st.sidebar.toggle("Enable Auto-Refresh (5s)", value=True)

# Initialize global tracking session state for selected contracts so they don't erase on refresh
if "selected_ce_strikes" not in st.session_state:
    st.session_state.selected_ce_strikes = set()
if "selected_pe_strikes" not in st.session_state:
    st.session_state.selected_pe_strikes = set()

# Stop execution if credentials are not provided via the website
if not app_id or not access_token:
    st.warning("👈 Please enter your FYERS App ID and Access Token in the sidebar to launch the live feed web link.")
    st.stop()

# Initialize FYERS client using the website input fields
@st.cache_resource
def get_fyers_client(client_id, token):
    return fyersModel.FyersModel(client_id=client_id, token=token, is_async=False)

fyers = get_fyers_client(app_id, access_token)

# --- 3. INSTRUMENT SELECTION DISPLAY ---
underlying = st.sidebar.selectbox("Underlying Index", ["NSE:NIFTY50-INDEX", "NSE:BANKNIFTY-INDEX", "NSE:FINNIFTY-INDEX"])
strike_count = st.sidebar.slider("Strikes Display Limit", min_value=10, max_value=40, value=20)

# Set up lot sizes based on index rules
lot_size = 75 if "BANKNIFTY" in underlying else (25 if "FINNIFTY" in underlying else 50)

# --- 4. FETCH REAL-TIME DATA STREAM ---
try:
    chain_payload = {"symbol": underlying, "strikecount": strike_count, "timestamp": ""}
    chain_response = fyers.optionchain(data=chain_payload)
    
    if chain_response.get("s") == "ok":
        raw_chain = chain_response["data"]["optionsChain"]
        df_raw = pd.DataFrame(raw_chain)
        
        idx_row = df_raw[df_raw['exchange'] == 10]
        if not idx_row.empty:
            spot_price = idx_row['ltp'].iloc[0]
            st.sidebar.metric(label="Live Index Spot Price", value=f"₹{spot_price:,.2f}")
        else:
            spot_price = df_raw['strike_price'].median()
    else:
        st.error(f"FYERS API Return Error: {chain_response.get('message')}")
        st.stop()
except Exception as e:
    st.error(f"Live API Sync Failed. Check if token is expired: {str(e)}")
    st.stop()

# --- 5. FORMAT CONFIGURATION LAYOUT ---
df_options = df_raw[df_raw['option_type'].isin(['CE', 'PE'])].copy()
ce_data = df_options[df_options['option_type'] == 'CE'][['strike_price', 'ltp', 'symbol']].rename(columns={'ltp': 'CE_LTP', 'symbol': 'CE_Symbol'})
pe_data = df_options[df_options['option_type'] == 'PE'][['strike_price', 'ltp', 'symbol']].rename(columns={'ltp': 'PE_LTP', 'symbol': 'PE_Symbol'})
option_matrix = pd.merge(ce_data, pe_data, on='strike_price').sort_values(by='strike_price').reset_index(drop=True)

# --- 6. INTERACTIVE CHAIN DESK MATRIX ---
st.title("📈 Standalone Strategy Builder Desk")
st.caption(f"Connected to FYERS API Feed • Active Lot Size: **{lot_size}** contracts")

h_cols = st.columns([1, 2, 1, 1, 1, 2, 1])
h_cols[0].write("**Select CE**")
h_cols[1].write("**CE Symbol**")
h_cols[2].write("**CE LTP**")
h_cols[3].write("**Strike**")
h_cols[4].write("**PE LTP**")
h_cols[5].write("**PE Symbol**")
h_cols[6].write("**Select PE**")

selected_legs = []

for idx, row in option_matrix.iterrows():
    is_atm = abs(row['strike_price'] - spot_price) <= (100 if "BANKNIFTY" in underlying else 50)
    bg_marker = "🧬 " if is_atm else ""
    
    cols = st.columns([1, 2, 1, 1, 1, 2, 1])
    
    # CE Selection State Persistence
    ce_state = row['strike_price'] in st.session_state.selected_ce_strikes
    ce_checked = cols[0].checkbox("CE", key=f"ce_chk_{idx}", value=ce_state, label_visibility="collapsed")
    if ce_checked:
        st.session_state.selected_ce_strikes.add(row['strike_price'])
        selected_legs.append({"Symbol": row['CE_Symbol'], "Type": "CE", "Strike": row['strike_price'], "LTP": row['CE_LTP']})
    else:
        st.session_state.selected_ce_strikes.discard(row['strike_price'])
        
    cols[1].write(f"`{row['CE_Symbol'].replace('NSE:', '')}`")
    cols[2].write(f"₹{row['CE_LTP']:.2f}")
    cols[3].write(f"{bg_marker}**{int(row['strike_price'])}**")
    cols[4].write(f"₹{row['PE_LTP']:.2f}")
    cols[5].write(f"`{row['PE_Symbol'].replace('NSE:', '')}`")
    
    # PE Selection State Persistence
    pe_state = row['strike_price'] in st.session_state.selected_pe_strikes
    pe_checked = cols[6].checkbox("PE", key=f"pe_chk_{idx}", value=pe_state, label_visibility="collapsed")
    if pe_checked:
        st.session_state.selected_pe_strikes.add(row['strike_price'])
        selected_legs.append({"Symbol": row['PE_Symbol'], "Type": "PE", "Strike": row['strike_price'], "LTP": row['PE_LTP']})
    else:
        st.session_state.selected_pe_strikes.discard(row['strike_price'])

# --- 7. STRATEGY CONSOLE MATRIX ---
if selected_legs:
    st.write("---")
    st.header("⚖️ Active Strategy Positions Matrix")
    managed_legs = []
    
    for idx, leg in enumerate(selected_legs):
        cc = st.columns([2, 1, 1, 1, 1])
        cc[0].write(f"**Leg {idx+1}:** `{leg['Symbol'].replace('NSE:', '')}`")
        action = cc[1].selectbox("Action", ["Buy", "Sell"], key=f"act_{idx}", label_visibility="collapsed")
        qty = cc[2].number_input("Lots", min_value=1, value=1, step=1, key=f"qty_{idx}", label_visibility="collapsed")
        
        direction = 1 if action == "Buy" else -1
        net_value = leg['LTP'] * direction * qty * lot_size
        managed_legs.append(net_value)
        
        cc[3].write(f"LTP: ₹{leg['LTP']:.2f}")
        cc[4].write(f"Net Premium: **₹{net_value:,.2f}**")
        
    total_cashflow = sum(managed_legs)
    st.write("---")
    
    m1, m2 = st.columns(2)
    if total_cashflow < 0:
        m1.metric(label="Net Strategy Value Position", value=f"₹{abs(total_cashflow):,.2f}", delta="Net Capital Outflow Debit", delta_color="inverse")
    else:
        m1.metric(label="Net Strategy Value Position", value=f"₹{total_cashflow:,.2f}", delta="Net Premium Credit Collected", delta_color="normal")
    m2.success("🔄 Streaming Active. The table retains your checked boxes while pricing ticks continuously.")

# --- 8. LIVE AUTO-REFRESH TRIGGER ---
if auto_refresh:
    time.sleep(5)
    st.rerun()
