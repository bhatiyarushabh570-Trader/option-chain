# app.py
import streamlit as st
import pandas as pd
import numpy as np
import scipy.stats as si
from fyers_apiv3 import fyersModel
import time
from datetime import datetime, timezone

st.set_page_config(layout="wide", page_title="FYERS Option Strategy Cockpit")

# --- 1. OPTION CHAIN MATHEMATICAL GREEKS ENGINE ---
def calculate_delta(S, K, DTE, iv_pct, option_type="CE"):
    """Calculates theoretical Black-Scholes absolute Delta for a single leg."""
    if DTE <= 0:
        return 1.0 if (option_type == "CE" and S > K) else (-1.0 if (option_type == "PE" and S < K) else 0.0)
    
    T = max(DTE / 365.0, 0.001)
    r = 0.0675  # 6.75% benchmark Indian Risk-Free interest rate
    sigma = max(iv_pct / 100.0, 0.01)
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    
    if option_type == "CE":
        return float(si.norm.cdf(d1))
    else:
        return float(si.norm.cdf(d1) - 1.0)

# --- 2. WEB USER INTERFACE SIDEBAR ---
st.sidebar.header("🔑 FYERS API Connectivity")
app_id = st.sidebar.text_input("FYERS App ID", type="password")
access_token = st.sidebar.text_input("Access Token / Auth Code", type="password")

st.sidebar.write("---")
st.sidebar.header("🔄 Live Refresh Engine")
auto_refresh = st.sidebar.toggle("Enable Auto-Refresh (5s)", value=True)

# Persistent Session Memory Containers across UI reload intervals
if "selected_ce_strikes" not in st.session_state:
    st.session_state.selected_ce_strikes = set()
if "selected_pe_strikes" not in st.session_state:
    st.session_state.selected_pe_strikes = set()

if not app_id or not access_token:
    st.warning("👈 Enter your active FYERS App ID and Access Token to stream options chains.")
    st.stop()

@st.cache_resource
def get_fyers_client(client_id, token):
    return fyersModel.FyersModel(client_id=client_id, token=token, is_async=False)

fyers = get_fyers_client(app_id, access_token)

underlying = st.sidebar.selectbox("Underlying Index", ["NSE:NIFTY50-INDEX", "NSE:BANKNIFTY-INDEX", "NSE:FINNIFTY-INDEX"])
strike_count = st.sidebar.slider("Strikes Display Limit", min_value=10, max_value=40, value=20)

# Compliant Post-Revision Lot Size Definitions
if "BANKNIFTY" in underlying:
    lot_size = 30
elif "FINNIFTY" in underlying:
    lot_size = 60
else:
    lot_size = 65

# --- 3. THE FIXED EXPIRY DATE PARSING LOOP ---
target_expiry_timestamp = ""  # Default empty queries near contracts initially
days_to_expiry = 7            # Fallback benchmark baseline

try:
    # Query with empty parameters to safely look up valid structural expiry list data payloads
    meta_payload = {"symbol": underlying, "strikecount": 2, "timestamp": ""}
    meta_response = fyers.optionchain(data=meta_payload)
    
    if meta_response.get("s") == "ok" and "expiryData" in meta_response["data"]:
        expiry_records = meta_response["data"]["expiryData"]
        
        # Build dictionary pairing user-friendly dates to the mandatory UNIX Epoch strings
        expiry_map = {item["date"]: str(item["timestamp"]) for item in expiry_records}
        expiry_display_list = list(expiry_map.keys())
        
        if expiry_display_list:
            selected_date = st.sidebar.selectbox("📅 Select Expiry Date", expiry_display_list)
            target_expiry_timestamp = expiry_map[selected_date]
            
            # Compute dynamic structural DTE values
            exp_date = datetime.strptime(selected_date, "%Y-%m-%d")
            days_to_expiry = max((exp_date - datetime.today()).days, 0)
except Exception as e:
    st.sidebar.warning(" Fetching expiry timelines from server...")

# --- 4. STREAM DATA CORRESPONDING TO CHOSEN EXPIRY TIMESTAMP ---
try:
    chain_payload = {"symbol": underlying, "strikecount": strike_count, "timestamp": target_expiry_timestamp}
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
        st.error(f"FYERS API Matrix Fault: {chain_response.get('message')}")
        st.stop()
except Exception as e:
    st.error(f"Live API Sync Blocked. Session token may have expired: {str(e)}")
    st.stop()

# --- 5. DATA EXTRACTION MATRICES MAPPING ---
df_options = df_raw[df_raw['option_type'].isin(['CE', 'PE'])].copy()
if 'iv' not in df_options.columns or df_options['iv'].isna().all():
    df_options['iv'] = 14.0  # Safe Indian Index structural fallback baseline

ce_data = df_options[df_options['option_type'] == 'CE'][['strike_price', 'ltp', 'symbol', 'iv']].rename(columns={'ltp': 'CE_LTP', 'symbol': 'CE_Symbol', 'iv': 'CE_IV'})
pe_data = df_options[df_options['option_type'] == 'PE'][['strike_price', 'ltp', 'symbol', 'iv']].rename(columns={'ltp': 'PE_LTP', 'symbol': 'PE_Symbol', 'iv': 'PE_IV'})
option_matrix = pd.merge(ce_data, pe_data, on='strike_price').sort_values(by='strike_price').reset_index(drop=True)

# --- 6. RENDER INTERACTIVE CHAIN VIEW MATRIX ---
st.title("📈 Delta-Neutral Option Strategy Desk")
st.caption(f"Streaming Engine Connected • Active Lot Size: **{lot_size}** contracts")

# Explicit Column Target Headers
cols_head = st.columns(7)
cols_head.write("**Select CE**")
cols_head.write("**CE Symbol**")
cols_head.write("**CE LTP**")
cols_head.write("**Strike**")
cols_head.write("**PE LTP**")
cols_head.write("**PE Symbol**")
cols_head.write("**Select PE**")

selected_legs = []

for idx, row in option_matrix.iterrows():
    is_atm = abs(row['strike_price'] - spot_price) <= (100 if "BANKNIFTY" in underlying else 50)
    bg_marker = "🧬 " if is_atm else ""
    
    cols = st.columns(7)
    
    # CE Component
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
    
    # PE Component
    pe_state = row['strike_price'] in st.session_state.selected_pe_strikes
    pe_checked = cols.checkbox("PE", key=f"pe_chk_{idx}", value=pe_state, label_visibility="collapsed")
    if pe_checked:
        st.session_state.selected_pe_strikes.add(row['strike_price'])
        selected_legs.append({"Symbol": row['PE_Symbol'], "Type": "PE", "Strike": row['strike_price'], "LTP": row['PE_LTP'], "IV": row['PE_IV']})
    else:
        st.session_state.selected_pe_strikes.discard(row['strike_price'])

# --- 7. REVISED COMPREHENSIVE STRATEGY CALCULATION ENGINE ---
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
        
        # Calculate individual leg raw theoretical Delta
        raw_delta = calculate_delta(spot_price, leg['Strike'], days_to_expiry, leg['IV'], leg['Type'])
        
        # FIXED POSITION ACCOUNTING MATH LOGIC:
        # Buying costs premium (-), Selling collects upfront credit (+)
        direction_premium = -1 if action == "Buy" else 1
        net_value = leg['LTP'] * direction_premium * qty * lot_size
        
        # Shorting an instrument completely flips its default directional risk Delta sign
        direction_delta = 1 if action == "Buy" else -1
        net_delta = raw_delta * direction_delta * qty * lot_size
        
        managed_premiums.append(net_value)
        managed_deltas.append(net_delta)
        
        cc.write(f"LTP: ₹{leg['LTP']:.2f}")
        cc.write(f"Leg Delta: `{raw_delta * direction_delta:+.3f}`")
        cc.write(f"Net Premium: **₹{net_value:,.2f}**")
        
    total_cashflow = sum(managed_premiums)
    total_net_delta = sum(managed_deltas)
    
    st.write("---")
    st.header("📊 Real-Time Portfolio Performance Cockpit")
    
    m1, m2, m3 = st.columns(3)
    
    # FIXED DEBIT VS CREDIT VIEW HOOK
    if total_cashflow < 0:
        m1.metric(label="Strategy Financial Setup Cost", value=f"₹{abs(total_cashflow):,.2f}", delta="🔴 NET DEBIT (Net Premium Paid Out)", delta_color="inverse")
    else:
        m1.metric(label="Strategy Financial Setup Cost", value=f"₹{total_cashflow:,.2f}", delta="🟢 NET CREDIT (Net Premium Collected)", delta_color="normal")
        
    # FIXED DIRECTIONAL DELTA-NEUTRAL SCOREBOARD 
    delta_status_text = "🎯 DELTA NEUTRAL BALANCE" if abs(total_net_delta) <= (lot_size * 0.1) else ("📈 BULLISH BIAS" if total_net_delta > 0 else "📉 BEARISH BIAS")
    m2.metric(label="Combined Portfolio Net Delta", value=f"{total_net_delta:+.2f}", delta=delta_status_text, delta_color="normal" if abs(total_net_delta) <= (lot_size * 0.1) else "inverse")
    
    # Dynamic Visual P&L Gauge Meter Setup
    if 'entry_cost_ref' not in st.session_state or st.session_state.get('reset_ref'):
        st.session_state.entry_cost_ref = total_cashflow
