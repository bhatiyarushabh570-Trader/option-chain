# app.py
import streamlit as st
import pandas as pd
import numpy as np
import scipy.stats as si
from fyers_apiv3 import fyersModel
import time
from datetime import datetime

st.set_page_config(layout="wide", page_title="Trader Strategy Desk")
st.title("⚡ Standalone Multi-Leg Option Desk")

# --- 1. COMPLETELY ISOLATED OPTION MATHEMATICS ENGINE ---
def get_clean_delta(S, K, DTE, option_type="CE"):
    try:
        if S <= 0 or K <= 0: return 0.0
        if DTE <= 0: return 1.0 if (option_type == "CE" and S > K) else (-1.0 if (option_type == "PE" and S < K) else 0.0)
        T = max(DTE / 365.0, 0.001)
        r, sigma = 0.0675, 0.14  # Safe benchmark Interest and IV parameters
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        return float(si.norm.cdf(d1)) if option_type == "CE" else float(si.norm.cdf(d1) - 1.0)
    except:
        return 0.5 if option_type == "CE" else -0.5

# --- 2. NO-HEADACHE WEB CONTENT CREDENTIALS ---
st.sidebar.header("🔑 API Access Keys")
app_id = st.sidebar.text_input("FYERS App ID", type="password")
access_token = st.sidebar.text_input("Access Token", type="password")
auto_refresh = st.sidebar.toggle("Enable Auto-Refresh (5s)", value=True)

if not app_id or not access_token:
    st.warning("👈 Please enter your active FYERS App ID and Access Token in the sidebar.")
    st.stop()

# Initialize API connection instantly without memory caching bugs
fyers = fyersModel.FyersModel(client_id=app_id, token=access_token, is_async=False)

underlying = st.sidebar.selectbox("Script", ["NSE:NIFTY50-INDEX", "NSE:BANKNIFTY-INDEX", "NSE:FINNIFTY-INDEX"])
lot_size = 30 if "BANKNIFTY" in underlying else (60 if "FINNIFTY" in underlying else 65)

# --- 3. CRASH-PROOF EXPIRY DATA EXTRACTION LAYER ---
expiry_stamp, days_to_expiry, spot_price = "", 7, 22000.0
expiry_list = []

try:
    init_res = fyers.optionchain(data={"symbol": underlying, "strikecount": 10, "timestamp": ""})
    if init_res.get("s") == "ok" and "data" in init_res:
        block = init_res["data"]
        raw_opts = block.get("optionsChain", [])
        
        # Pull expiry lists safely
        if block.get("expiryData"):
            expiry_list = [item["date"] for item in block["expiryData"] if "date" in item]
        else:
            expiry_list = sorted(list(set([o["expiry"] for o in raw_opts if "expiry" in o])))
            
        if expiry_list:
            chosen_date = st.sidebar.selectbox("📅 Select Expiry Date", expiry_list)
            try:
                days_to_expiry = max((datetime.strptime(chosen_date, "%Y-%m-%d") - datetime.today()).days, 0)
            except:
                days_to_expiry = 7
                
            # Grab matching UNIX timestamp key safely
            if block.get("expiryData"):
                for item in block["expiryData"]:
                    if item.get("date") == chosen_date: expiry_stamp = str(item.get("timestamp", ""))
            
        # Pull spot index parameters safely
        final_res = fyers.optionchain(data={"symbol": underlying, "strikecount": 20, "timestamp": expiry_stamp})
        if final_res.get("s") == "ok":
            df_build = pd.DataFrame(final_res["data"]["optionsChain"])
        else:
            df_build = pd.DataFrame(raw_opts)
            
        idx_row = df_build[df_build['exchange'] == 10]
        spot_price = float(idx_row['ltp'].iloc[0]) if not idx_row.empty else float(df_build['strike_price'].median())
        st.sidebar.metric(label="Live Index Spot Price", value=f"₹{spot_price:,.2f}")
except:
    st.sidebar.error("⚠️ API connection timeout. Verify if your daily session token has expired.")
    st.stop()

# --- 4. STREAMLINED BULLETPROOF DATA STRUCTURE BUILDER ---
try:
    df_clean = df_build[df_build['option_type'].isin(['CE', 'PE'])].copy()
    ce_df = df_clean[df_clean['option_type'] == 'CE'][['strike_price', 'ltp', 'symbol']].rename(columns={'ltp': 'CE_LTP', 'symbol': 'CE_Symbol'})
    pe_df = df_clean[df_clean['option_type'] == 'PE'][['strike_price', 'ltp', 'symbol']].rename(columns={'ltp': 'PE_LTP', 'symbol': 'PE_Symbol'})
    matrix = pd.merge(ce_df, pe_df, on='strike_price').sort_values(by='strike_price').reset_index(drop=True)
except:
    st.error("Could not construct option chain matrix layout from broker dataset.")
    st.stop()

# --- 5. IMMUNE SELECTION INTERFACE BLOCK ---
st.header("1. Live Option Chain Desk")
st.caption(f"Check box labels to queue contracts. Active Lot Size configuration: **{lot_size}**")

# Native Streamlit data frame display is completely crash-immune compared to column layouts
display_matrix = matrix.copy()
display_matrix['Strike'] = display_matrix['strike_price'].astype(int)
display_matrix = display_matrix[['CE_Symbol', 'CE_LTP', 'Strike', 'PE_LTP', 'PE_Symbol']]
st.dataframe(display_matrix, use_container_width=True, height=350)

# Multi-select dropdown menus replace faulty individual checkbox bugs entirely
st.subheader("🛠️ Strategy Assembly Console")
selected_ce = st.multiselect("➕ Queue Call Options (CE) by Strike Price:", matrix['strike_price'].unique(), key="ce_sel")
selected_pe = st.multiselect("➕ Queue Put Options (PE) by Strike Price:", matrix['strike_price'].unique(), key="pe_sel")

# Harvest selected array payloads into state maps
active_legs = []
for s in selected_ce:
    match = matrix[matrix['strike_price'] == s].iloc[0]
    active_legs.append({"Symbol": match['CE_Symbol'], "Type": "CE", "Strike": s, "LTP": float(match['CE_LTP'])})
for s in selected_pe:
    match = matrix[matrix['strike_price'] == s].iloc[0]
    active_legs.append({"Symbol": match['PE_Symbol'], "Type": "PE", "Strike": s, "LTP": float(match['PE_LTP'])})

# --- 6. CRASH-PROOF PERFORMANCE METRICS ENGINE ---
if active_legs:
    st.write("---")
    st.header("⚖️ Active Strategy Positions Matrix")
    
    total_net_delta = 0.0
    total_strategy_pnl = 0.0
    total_entry_credit_debit = 0.0
    
    for idx, leg in enumerate(active_legs):
        # Wrap each leg in a secure dedicated block to completely isolate configuration data
        with st.container():
            c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 2])
            c1.write(f"**Leg {idx+1}:** `{leg['Symbol'].replace('NSE:', '')}`")
            action = c2.selectbox("Side", ["Sell", "Buy"], key=f"action_{idx}")
            lots = c3.number_input("Lots", min_value=1, value=1, step=1, key=f"lots_{idx}")
            entry_price = c4.number_input("Entry (Limit)", min_value=0.0, value=leg['LTP'], step=0.05, key=f"entry_{idx}")
            
            # Position Math logic
            raw_delta = get_clean_delta(spot_price, leg['Strike'], days_to_expiry, leg['Type'])
            dir_delta = -1 if action == "Sell" else 1
            leg_delta = raw_delta * dir_delta * lots * lot_size
            total_net_delta += leg_delta
            
            if action == "Sell":
                leg_pnl = (entry_price - leg['LTP']) * lots * lot_size
                leg_value = entry_price * lots * lot_size
            else:
                leg_pnl = (leg['LTP'] - entry_price) * lots * lot_size
                leg_value = -entry_price * lots * lot_size
                
            total_strategy_pnl += leg_pnl
            total_entry_credit_debit += leg_value
            
            pnl_text = f"🟢 +₹{leg_pnl:,.2f}" if leg_pnl >= 0 else f"🔴 -₹{abs(leg_pnl):,.2f}"
            c5.write(f"LTP: ₹{leg['LTP']:.2f} | Delta: `{raw_delta*dir_delta:+.3f}` | P&L: **{pnl_text}**")
            
    st.write("---")
    st.header("📊 Real-Time Portfolio Performance Cockpit")
    m1, m2, m3 = st.columns(3)
    
    if total_entry_credit_debit >= 0:
        m1.metric(label="Position Flow Type", value=f"₹{total_entry_credit_debit:,.2f}", delta="🟢 NET CREDIT COLLECTED", delta_color="normal")
    else:
        m1.metric(label="Position Flow Type", value=f"₹{abs(total_entry_credit_debit):,.2f}", delta="🔴 NET DEBIT PAID", delta_color="inverse")
        
    delta_lbl = "🎯 DELTA NEUTRAL BALANCE" if abs(total_net_delta) <= (lot_size * 0.1) else ("📈 BULLISH BIAS" if total_net_delta > 0 else "📉 BEARISH BIAS")
    m2.metric(label="Combined Net Delta", value=f"{total_net_delta:+.2f}", delta=delta_lbl)
    
    if total_strategy_pnl >= 0:
        m3.metric(label="🔥 Combined Live Strategy P&L", value=f"₹{total_strategy_pnl:,.2f}", delta="🟢 POSITIVE RETURN")
    else:
        m3.metric(label="🔥 Combined Live Strategy P&L", value=f"-₹{abs(total_strategy_pnl):,.2f}", delta="🔴 RUNNING LOSS BALANCE", delta_color="inverse")

if auto_refresh:
    time.sleep(5)
    st.rerun()
