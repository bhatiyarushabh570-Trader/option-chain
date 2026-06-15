# app.py
import streamlit as st
import pandas as pd
import numpy as np
import scipy.stats as si
from fyers_apiv3 import fyersModel
import time
from datetime import datetime

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

# --- 3. SAFE RECURSIVE HANDSHAKE FOR LIVE STREAM & EXPIRY DATA ---
target_expiry_timestamp = ""  
days_to_expiry = 7            
df_raw = pd.DataFrame()

try:
    base_payload = {"symbol": underlying, "strikecount": strike_count, "timestamp": ""}
    base_response = fyers.optionchain(data=base_payload)
    
    if base_response.get("s") == "ok" and "data" in base_response:
        chain_data_block = base_response["data"]
        
        expiry_list = []
        expiry_map = {}
        
        if "expiryData" in chain_data_block and chain_data_block["expiryData"]:
            for item in chain_data_block["expiryData"]:
                if "date" in item:
                    expiry_list.append(item["date"])
                    expiry_map[item["date"]] = str(item.get("timestamp", ""))
        else:
            raw_options = chain_data_block.get("optionsChain", [])
            for opt in raw_options:
                if "expiry" in opt:
                    expiry_list.append(opt["expiry"])
                    expiry_map[opt["expiry"]] = str(opt.get("expiry_timestamp", ""))
            expiry_list = sorted(list(set(expiry_list)))

        if expiry_list:
            selected_date = st.sidebar.selectbox("📅 Select Expiry Date", expiry_list)
            target_expiry_timestamp = expiry_map.get(selected_date, "")
            
            try:
                exp_date = datetime.strptime(selected_date, "%Y-%m-%d")
                days_to_expiry = max((exp_date - datetime.today()).days, 0)
            except Exception:
                days_to_expiry = 7
        
        if target_expiry_timestamp:
            targeted_payload = {"symbol": underlying, "strikecount": strike_count, "timestamp": target_expiry_timestamp}
            targeted_response = fyers.optionchain(data=targeted_payload)
            if targeted_response.get("s") == "ok" and "optionsChain" in targeted_response.get("data", {}):
                df_raw = pd.DataFrame(targeted_response["data"]["optionsChain"])
        
        if df_raw.empty and "optionsChain" in chain_data_block:
            df_raw = pd.DataFrame(chain_data_block["optionsChain"])
            
        if not df_raw.empty:
            idx_row = df_raw[df_raw['exchange'] == 10]
            if not idx_row.empty:
                spot_price = idx_row['ltp'].iloc
            else:
                spot_price = df_raw['strike_price'].median()
            st.sidebar.metric(label="Live Index Spot Price", value=f"₹{spot_price:,.2f}")
        else:
            st.error("No options data returned from server. Ensure your token is fresh.")
            st.stop()
    else:
        st.error(f"FYERS API Matrix Fault: {base_response.get('message', 'Verify your Access Token is active for today.')}")
        st.stop()
except Exception as e:
    st.error(f"Live API Sync Blocked. Session token may have expired or data structure changed: {str(e)}")
    st.stop()

# --- 4. DATA EXTRACTION MATRICES MAPPING ---
df_options = df_raw[df_raw['option_type'].isin(['CE', 'PE'])].copy()
if 'iv' not in df_options.columns or df_options['iv'].isna().all():
    df_options['iv'] = 14.0  

ce_data = df_options[df_options['option_type'] == 'CE'][['strike_price', 'ltp', 'symbol', 'iv']].rename(columns={'ltp': 'CE_LTP', 'symbol': 'CE_Symbol', 'iv': 'CE_IV'})
pe_data = df_options[df_options['option_type'] == 'PE'][['strike_price', 'ltp', 'symbol', 'iv']].rename(columns={'ltp': 'PE_LTP', 'symbol': 'PE_Symbol', 'iv': 'PE_IV'})
option_matrix = pd.merge(ce_data, pe_data, on='strike_price').sort_values(by='strike_price').reset_index(drop=True)

# --- 5. RENDER INTERACTIVE CHAIN VIEW MATRIX ---
st.title("📈 Delta-Neutral Option Strategy Desk")
st.caption(f"Streaming Engine Connected • Active Lot Size: **{lot_size}** contracts")

# FIXED: Explicitly write to each unique column index object in the headers row array
cols_head = st.columns(7)
cols_head[0].write("**Select CE**")
cols_head[1].write("**CE Symbol**")
cols_head[2].write("**CE LTP**")
cols_head[3].write("**Strike**")
cols_head[4].write("**PE LTP**")
cols_head[5].write("**PE Symbol**")
cols_head[6].write("**Select PE**")

selected_legs = []

for idx, row in option_matrix.iterrows():
    is_atm = abs(row['strike_price'] - spot_price) <= (100 if "BANKNIFTY" in underlying else 50)
    bg_marker = "🧬 " if is_atm else ""
    
    cols = st.columns(7)
    
    # CE Selection Checkbox
    ce_state = row['strike_price'] in st.session_state.selected_ce_strikes
    ce_checked = cols[0].checkbox("CE", key=f"ce_chk_{idx}", value=ce_state, label_visibility="collapsed")
    if ce_checked:
        st.session_state.selected_ce_strikes.add(row['strike_price'])
        selected_legs.append({"Symbol": row['CE_Symbol'], "Type": "CE", "Strike": row['strike_price'], "LTP": row['CE_LTP'], "IV": row['CE_IV']})
    else:
        st.session_state.selected_ce_strikes.discard(row['strike_price'])
        
    cols[1].write(f"`{row['CE_Symbol'].replace('NSE:', '')}`")
    cols[2].write(f"₹{row['CE_LTP']:.2f}")
    cols[3].write(f"{bg_marker}**{int(row['strike_price'])}**")
    cols[4].write(f"₹{row['PE_LTP']:.2f}")
    cols[5].write(f"`{row['PE_Symbol'].replace('NSE:', '')}`")
    
    # PE Selection Checkbox
    pe_state = row['strike_price'] in st.session_state.selected_pe_strikes
    pe_checked = cols[6].checkbox("PE", key=f"pe_chk_{idx}", value=pe_state, label_visibility="collapsed")
    if pe_checked:
        st.session_state.selected_pe_strikes.add(row['strike_price'])
        selected_legs.append({"Symbol": row['PE_Symbol'], "Type": "PE", "Strike": row['strike_price'], "LTP": row['PE_LTP'], "IV": row['PE_IV']})
    else:
        st.session_state.selected_pe_strikes.discard(row['strike_price'])

# --- 6. ADVANCED STRATEGY CONSOLE WITH CUSTOM LIMIT ENTRY PRICES ---
if selected_legs:
    st.write("---")
    st.header("⚖️ Active Strategy Positions Matrix")
    
    # FIXED: Explicitly write to each column index for the lower table headers row
    sc_head = st.columns(7)
    sc_head[0].write("**Leg Definition**")
    sc_head[1].write("**Action**")
    sc_head[2].write("**Lots**")
    sc_head[3].write("**Entry Price (Limit)**")
    sc_head[4].write("**Current LTP**")
    sc_head[5].write("**Leg Delta**")
    sc_head[6].write("**Net P&L**")
    
    total_net_delta = 0.0
    total_strategy_pnl = 0.0
    total_entry_value = 0.0
    
    for idx, leg in enumerate(selected_legs):
        cc = st.columns(7)
        cc[0].write(f"**Leg {idx+1}:** `{leg['Symbol'].replace('NSE:', '')}`")
        
        # Position Parameter Inputs
        action = cc[1].selectbox("Action", ["Buy", "Sell"], key=f"act_{idx}", label_visibility="collapsed")
        qty = cc[2].number_input("Lots", min_value=1, value=1, step=1, key=f"qty_{idx}", label_visibility="collapsed")
        
        # Interactive Limit Entry Price Input
        entry_limit = cc[3].number_input("Entry Price", min_value=0.0, value=float(leg['LTP']), step=0.05, key=f"ent_{idx}", label_visibility="collapsed")
        
        # Real-time Greeks calculation
        raw_delta = calculate_delta(spot_price, leg['Strike'], days_to_expiry, leg['IV'], leg['Type'])
        direction_delta = 1 if action == "Buy" else -1
        leg_net_delta = raw_delta * direction_delta * qty * lot_size
        total_net_delta += leg_net_delta
        
        # P&L Accounting Math Logic
        if action == "Buy":
            leg_pnl = (leg['LTP'] - entry_limit) * qty * lot_size
            leg_entry_premium = -entry_limit * qty * lot_size
        else:
            leg_pnl = (entry_limit - leg['LTP']) * qty * lot_size
            leg_entry_premium = entry_limit * qty * lot_size
            
        total_strategy_pnl += leg_pnl
