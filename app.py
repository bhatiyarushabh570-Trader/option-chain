# app.py
import streamlit as st
import pandas as pd
import numpy as np
import scipy.stats as si
from fyers_apiv3 import fyersModel
import time
from datetime import datetime

st.set_page_config(layout="wide", page_title="Live Strategy Desk & P&L Meter")

# --- 1. BLACK-SCHOLES ENGINE FOR REAL-TIME DELTA ---
def calculate_delta(S, K, DTE, iv_pct, option_type="CE"):
    """Calculates directional Delta for a single leg option on the fly."""
    if DTE <= 0:
        return 1.0 if (option_type == "CE" and S > K) else (-1.0 if (option_type == "PE" and S < K) else 0.0)
    
    T = DTE / 365.0
    r = 0.0675  # Approximate 6.75% current Indian Risk-Free Rate
    sigma = max(iv_pct / 100.0, 0.01) # Avoid division by zero
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    
    if option_type == "CE":
        return float(si.norm.cdf(d1))
    else:
        return float(si.norm.cdf(d1) - 1.0)

# --- 2. WEB-BASED AUTHENTICATION PROMPT ---
st.sidebar.header("🔑 FYERS API Connectivity")
app_id = st.sidebar.text_input("FYERS App ID", type="password")
access_token = st.sidebar.text_input("Access Token / Auth Code", type="password")

# --- 3. AUTOMATIC LIVE REFRESH CONTROLS ---
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

# --- 4. INSTRUMENT SELECTION & REVISED LOT SIZES ---
underlying = st.sidebar.selectbox("Underlying Index", ["NSE:NIFTY50-INDEX", "NSE:BANKNIFTY-INDEX", "NSE:FINNIFTY-INDEX"])
strike_count = st.sidebar.slider("Strikes Display Limit", min_value=10, max_value=40, value=20)

# COMPLIANT NEW SELECTION LOT SIZES 
if "BANKNIFTY" in underlying:
    lot_size = 30
elif "FINNIFTY" in underlying:
    lot_size = 60
else:
    lot_size = 65  # Nifty 50 updated from 50 to 65

# --- 5. EXPIRES FILTER ENGINE & DTE TRACKER ---
expiry_to_fetch = ""  
days_to_expiry = 7 # Fallback average default
try:
    meta_payload = {"symbol": underlying, "strikecount": 2, "timestamp": ""}
    meta_response = fyers.optionchain(data=meta_payload)
    
    if meta_response.get("s") == "ok" and "expiryData" in meta_response["data"]:
        expiry_list = [item["date"] for item in meta_response["data"]["expiryData"]]
        selected_expiry = st.sidebar.selectbox("📅 Select Expiry Date", expiry_list)
        expiry_to_fetch = selected_expiry
        
        # Calculate dynamic DTE
        exp_date = datetime.strptime(selected_expiry, "%Y-%m-%d")
        days_to_expiry = max((exp_date - datetime.today()).days, 0)
except Exception as e:
    pass

# --- 6. FETCH REAL-TIME DATA STREAM FOR SELECTED EXPIRY ---
try:
    chain_payload = {"symbol": underlying, "strikecount": strike_count, "timestamp": expiry_to_fetch}
    chain_response = fyers.optionchain(data=chain_payload)
    
    if chain_response.get("s") == "ok":
        raw_chain = chain_response["data"]["optionsChain"]
        df_raw = pd.DataFrame(raw_chain)
        
        idx_row = df_raw[df_raw['exchange'] == 10]
        if not idx_row.empty:
            spot_price = idx_row['ltp'].iloc
            st.sidebar.metric(label="Live Index Spot Price", value=f"₹{spot_price:,.2f}")
        else:
            spot_price = df_raw['strike_price'].median()
    else:
        st.error(f"FYERS API Return Error: {chain_response.get('message')}")
        st.stop()
except Exception as e:
    st.error(f"Live API Sync Failed. Check if token is expired: {str(e)}")
    st.stop()

# --- 7. FORMAT CONFIGURATION LAYOUT ---
df_options = df_raw[df_raw['option_type'].isin(['CE', 'PE'])].copy()

# Ensure IV field exists or fall back to an average benchmark
if 'iv' not in df_options.columns:
    df_options['iv'] = 14.0

ce_data = df_options[df_options['option_type'] == 'CE'][['strike_price', 'ltp', 'symbol', 'iv']].rename(columns={'ltp': 'CE_LTP', 'symbol': 'CE_Symbol', 'iv': 'CE_IV'})
pe_data = df_options[df_options['option_type'] == 'PE'][['strike_price', 'ltp', 'symbol', 'iv']].rename(columns={'ltp': 'PE_LTP', 'symbol': 'PE_Symbol', 'iv': 'PE_IV'})
option_matrix = pd.merge(ce_data, pe_data, on='strike_price').sort_values(by='strike_price').reset_index(drop=True)

# --- 8. INTERACTIVE CHAIN DESK MATRIX ---
st.title("📈 Multi-Leg Trading Dashboard & P&L Meter")
st.caption(f"Connected to FYERS API Feed • Active Lot Size: **{lot_size}** contracts per lot.")

h_cols = st.columns(7)
h_cols.write("**Select CE**")
h_cols.write("**CE Symbol**")
h_cols.write("**CE LTP**")
h_cols.write("**Strike**")
h_cols.write("**PE LTP**")
h_cols.write("**PE Symbol**")
h_cols.write("**Select PE**")

selected_legs = []

for idx, row in option_matrix.iterrows():
    is_atm = abs(row['strike_price'] - spot_price) <= (100 if "BANKNIFTY" in underlying else 50)
    bg_marker = "🧬 " if is_atm else ""
    
    cols = st.columns(7)
    
    # CE Selection
    ce_state = row['strike_price'] in st.session_state.selected_ce_strikes
    ce_checked = cols.checkbox("CE", key=f"ce_chk_{idx}", value=ce_state, label_visibility="collapsed")
    if ce_checked:
        st.session_state.selected_ce_strikes.add(row['strike_price'])
        selected_legs.append({"Symbol": row['CE_Symbol'], "Type": "CE", "Strike": row['strike_price'], "LTP": row['CE_LTP'], "IV": row['CE_IV']})
    else:
        st.session_state.selected_ce_strikes.discard(row['strike_price'])
        
    cols.write(f"`{row['CE_Symbol'].replace('NSE:', '')}`")
    cols.write(f"₹{row['CE_LTP']:.2f}")
    cols.write(f"{bg_marker}**{int(row['strike_price'])}**")
    cols.write(f"₹{row['PE_LTP']:.2f}")
    cols.write(f"`{row['PE_Symbol'].replace('NSE:', '')}`")
    
    # PE Selection
    pe_state = row['strike_price'] in st.session_state.selected_pe_strikes
    pe_checked = cols.checkbox("PE", key=f"pe_chk_{idx}", value=pe_state, label_visibility="collapsed")
    if pe_checked:
        st.session_state.selected_pe_strikes.add(row['strike_price'])
        selected_legs.append({"Symbol": row['PE_Symbol'], "Type": "PE", "Strike": row['strike_price'], "LTP": row['PE_LTP'], "IV": row['PE_IV']})
    else:
        st.session_state.selected_pe_strikes.discard(row['strike_price'])

# --- 9. STRATEGY CONSOLE MATRIX WITH DETAILED GREEKS ---
if selected_legs:
    st.write("---")
    st.header("⚖️ Active Strategy Positions Matrix")
    
    managed_premiums = []
    managed_deltas = []
    
    for idx, leg in enumerate(selected_legs):
        cc = st.columns(6)
        cc.write(f"**Leg {idx+1}:** `{leg['Symbol'].replace('NSE:', '')}`")
        action = cc.selectbox("Action", ["Buy", "Sell"], key=f"act_{idx}", label_visibility="collapsed")
        qty = cc.number_input("Lots", min_value=1, value=1, step=1, key=f"qty_{idx}", label_visibility="collapsed")
        
        # Calculate individual directional Greek Delta
        raw_delta = calculate_delta(spot_price, leg['Strike'], days_to_expiry, leg['IV'], leg['Type'])
        
        direction = 1 if action == "Buy" else -1
        net_value = leg['LTP'] * direction * qty * lot_size
        net_delta = raw_delta * direction * qty * lot_size
        
        managed_premiums.append(net_value)
        managed_deltas.append(net_delta)
        
        cc.write(f"LTP: ₹{leg['LTP']:.2f}")
        cc.write(f"Delta: `{raw_delta:+.3f}`")
        cc.write(f"Net Value: **₹{net_value:,.2f}**")
        
    total_cashflow = sum(managed_premiums)
    total_net_delta = sum(managed_deltas)
    
    st.write("---")
    st.header("📊 Real-Time Portfolio Performance Cockpit")
    
    # Render combined analytical metric cards
    m1, m2, m3 = st.columns(3)
    
    if total_cashflow < 0:
        m1.metric(label="Strategy Total Premium Cost", value=f"₹{abs(total_cashflow):,.2f}", delta="Net Capital Debit", delta_color="inverse")
    else:
        m1.metric(label="Strategy Entry Credit Capital", value=f"₹{total_cashflow:,.2f}", delta="Net Premium Credit", delta_color="normal")
        
    m2.metric(label="Combined Portfolio Net Delta", value=f"{total_net_delta:+.2f}", 
              delta=f"Equivalent to {total_net_delta:,.1f} Underlying Shares", delta_color="normal" if abs(total_net_delta) < 10 else "inverse")
    
    # Dynamic Visual P&L Gauge Meter Setup
    # Simulates real-time variance based on entry capital reference
    if 'entry_cost_ref' not in st.session_state or st.session_state.get('reset_ref'):
        st.session_state.entry_cost_ref = total_cashflow
        st.session_state.reset_ref = False
        
    current_pnl = total_cashflow - st.session_state.entry_cost_ref
    
    if current_pnl >= 0:
        m3.metric(label="🔥 Live Active P&L State", value=f"₹{current_pnl:,.2f}", delta="🟢 IN THE GREEN (Profit Tracking)", delta_color="normal")
    else:
        m3.metric(label="🔥 Live Active P&L State", value=f"-₹{abs(current_pnl):,.2f}", delta="🔴 IN THE RED (Loss Tracking)", delta_color="inverse")
        
    # Visual Progress/Meter Bar Layout
    st.write("**Strategy Running P&L Gauge Meter:**")
    max_boundary = max(abs(st.session_state.entry_cost_ref) * 0.1, 5000) # 10% movement stop band reference
    progress_ratio = (current_pnl + max_boundary) / (max_boundary * 2)
    progress_ratio = max(min(progress_ratio, 1.0), 0.0) # Clamp between 0 and 1
    
