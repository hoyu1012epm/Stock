import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import datetime
import json
import gspread
from google.oauth2.service_account import Credentials

# 1. 網頁基本設定
st.set_page_config(page_title="專屬量化操盤副駕 | 雙引擎版", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# ☁️ 雲端資料庫連線設定
# ==========================================
@st.cache_resource(ttl=3600)
def init_connection():
    try:
        raw_json = st.secrets["GOOGLE_JSON"]
        creds_json = json.loads(raw_json, strict=False) 
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        client = gspread.authorize(creds)
        sh = client.open("Stock_Database")
        try: ws_users = sh.worksheet("Users")
        except:
            ws_users = sh.add_worksheet(title="Users", rows="100", cols="5")
            ws_users.append_row(["Username", "Password", "Initial_Capital", "Cash_Balance"])
        try: ws_holdings = sh.worksheet("Holdings")
        except:
            ws_holdings = sh.add_worksheet(title="Holdings", rows="1000", cols="6")
            ws_holdings.append_row(["Username", "Ticker", "Shares", "Entry_Price", "Total_Cost", "Buy_Date"])
        return sh
    except Exception as e:
        st.error(f"🚨 資料庫連線失敗！錯誤代碼: {e}")
        return None

sh = init_connection()

# ==========================================
# 🔐 登入系統與全域變數初始化
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.update({
        "logged_in": False, "username": "", "cash_balance": 0.0, 
        "market_fetched": False, "market_scores": {'total': 0},
        "user_holdings": pd.DataFrame(), "total_mkt_val": 0
    })

if not st.session_state["logged_in"]:
    st.title("🔐 專屬量化操盤副駕 - 登入系統")
    tab_login, tab_signup = st.tabs(["登入", "註冊新帳號"])
    with tab_login:
        login_user = st.text_input("帳號 (Username)", key="log_user")
        login_pwd = st.text_input("密碼 (Password)", type="password", key="log_pwd")
        if st.button("登入系統", type="primary"):
            if sh:
                df_users = pd.DataFrame(sh.worksheet("Users").get_all_records())
                if not df_users.empty and login_user in df_users["Username"].values:
                    user_row = df_users[df_users["Username"] == login_user].iloc[0]
                    if str(user_row["Password"]) == login_pwd:
                        st.session_state.update({"logged_in": True, "username": login_user, "cash_balance": float(user_row["Cash_Balance"])})
                        st.rerun()
                    else: st.error("密碼錯誤！")
                else: st.error("找不到此帳號，請先註冊！")
    with tab_signup:
        sign_user = st.text_input("設定帳號 (Username)", key="sig_user")
        sign_pwd = st.text_input("設定密碼 (Password)", type="password", key="sig_pwd")
        init_cap = st.number_input("初始投資本金 (NTD)", min_value=10000, value=1000000, step=10000)
        if st.button("註冊並建立帳本"):
            if sh and sign_user and sign_pwd:
                ws_users = sh.worksheet("Users")
                df_users = pd.DataFrame(ws_users.get_all_records()) if ws_users.get_all_records() else pd.DataFrame(columns=["Username"])
                if sign_user in df_users["Username"].values: st.error("此帳號已被使用！")
                else:
                    ws_users.append_row([sign_user, sign_pwd, init_cap, init_cap])
                    st.success("🎉 註冊成功！請切換到「登入」分頁。")
    st.stop() 

# ==========================================
# 📊 核心運算函數
# ==========================================
@st.cache_data(ttl=86400)
def get_stock_name(ticker):
    try: return yf.Ticker(ticker).info.get('shortName', ticker)
    except: return ticker

@st.cache_data(ttl=3600)
def load_data(ticker, days=1825): 
    df = yf.download(ticker, start=datetime.datetime.now() - datetime.timedelta(days=days), end=datetime.datetime.now(), progress=False)
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    if not df.empty: df.index = pd.to_datetime(df.index).tz_localize(None)
    return df

def apply_cooldown(signal_series, cooldown_period):
    clean_signal = pd.Series(False, index=signal_series.index)
    last_signal_idx = -cooldown_period - 1
    for i, val in enumerate(signal_series):
        if val and (i - last_signal_idx) > cooldown_period:
            clean_signal.iloc[i] = True
            last_signal_idx = i
    return clean_signal

def calculate_indicators(df, bbw_f, vol_f, kd_thresh, use_adx, cooldown, bias_limit):
    if len(df) < 60: return df 
    df['SMA_5'] = df['Close'].rolling(5).mean()
    df['SMA_20'] = df['Close'].rolling(20).mean()
    df['SMA_60'] = df['Close'].rolling(60).mean()
    df['STD_20'] = df['Close'].rolling(20).std()
    df['Upper_Band'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['Lower_Band'] = df['SMA_20'] - (df['STD_20'] * 2)
    df['BBW'] = (df['Upper_Band'] - df['Lower_Band']) / df['SMA_20']
    
    df['MACD'] = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Histogram'] = df['MACD'] - df['Signal']
    
    df['9MA_Max'] = df['High'].rolling(9).max()
    df['9MA_Min'] = df['Low'].rolling(9).min()
    df['RSV'] = (df['Close'] - df['9MA_Min']) / (df['9MA_Max'] - df['9MA_Min']) * 100
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    
    delta = df['Close'].diff()
    rs = delta.clip(lower=0).ewm(com=13, adjust=False).mean() / (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + rs))
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
    df['Bias_20MA'] = (df['Close'] - df['SMA_20']) / df['SMA_20'] * 100
    
    conditions = [(df['RSI'] >= 70) | (df['Bias_20MA'] >= bias_limit), (df['RSI'] >= 60) | (df['Bias_20MA'] >= (bias_limit * 0.7)), (df['Close'] < df['SMA_60'])]
    df['Status_Signal'] = np.select(conditions, ["🔴 極度危險", "🟡 留意拉回", "⚫ 空頭趨勢"], default="🟢 安全區間")
    df['Hover_Text'] = "20MA乖離: " + df['Bias_20MA'].round(2).astype(str) + "%<br>RSI: " + df['RSI'].round(1).astype(str) + "<br>判定: <b>" + df['Status_Signal'] + "</b>"
    
    df['TR'] = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Close'].shift(1)), abs(df['Low'] - df['Close'].shift(1))))
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']), np.maximum(df['High'] - df['High'].shift(1), 0), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)), np.maximum(df['Low'].shift(1) - df['Low'], 0), 0)
    df['ATR_14'] = df['TR'].ewm(alpha=1/14, adjust=False).mean()
    df['+DI'] = 100 * (df['+DM'].ewm(alpha=1/14, adjust=False).mean() / df['ATR_14'])
    df['-DI'] = 100 * (df['-DM'].ewm(alpha=1/14, adjust=False).mean() / df['ATR_14'])
    df['DX'] = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = df['DX'].ewm(alpha=1/14, adjust=False).mean()
    
    adx_cond = (df['ADX'] > 20) if use_adx else True
    df['Vol_5MA'] = df['Volume'].rolling(5).mean()
    
    df['Breakout_Raw'] = (df['BBW'] <= df['BBW'].rolling(20).min() * bbw_f).rolling(5).max().fillna(0).astype(bool) & (df['Close'] > df['Upper_Band']) & (df['Volume'] > df['Vol_5MA'] * vol_f) & (df['Close'] > df['SMA_60']) & adx_cond
    df['Pullback_Raw'] = (df['K'] > df['D']) & (df['K'].shift(1) <= df['D'].shift(1)) & (df['K'] <= kd_thresh) & (df['Close'] > df['SMA_60']) & adx_cond
    df['MABounce_Raw'] = (df['SMA_5'] > df['SMA_20']) & (df['SMA_20'] > df['SMA_60']) & (df['Low'] <= (df['SMA_20'] * 1.015)) & (df['Close'] > df['SMA_20']) & (df['Close'] > df['Open']) & adx_cond
    df['5MABounce_Raw'] = (df['SMA_5'] > df['SMA_20']) & (df['Close'] > df['SMA_20']) & (df['Low'] <= (df['SMA_5'] * 1.015)) & (df['Close'] > df['SMA_5']) & (df['Close'] > df['Open']) & adx_cond

    df['Sell_5MA_Raw'] = (df['Close'] < df['SMA_5']) & (df['Close'].shift(1) >= df['SMA_5'].shift(1))
    df['Sell_KD_Raw'] = (df['K'] < df['D']) & (df['K'].shift(1) >= df['D'].shift(1)) & (df['K'].shift(1) >= 80)
    df['Sell_RSI_Raw'] = (df['RSI'] < 70) & (df['RSI'].shift(1) >= 70)
    df['Sell_MACD_Raw'] = (df['MACD'] < df['Signal']) & (df['MACD'].shift(1) >= df['Signal'].shift(1))
    df['Sell_MA20_Raw'] = (df['Close'] < df['SMA_20']) & (df['Close'].shift(1) >= df['SMA_20'].shift(1))

    df['Buy_Breakout'] = apply_cooldown(df['Breakout_Raw'], cooldown); df['Buy_Pullback'] = apply_cooldown(df['Pullback_Raw'], cooldown)
    df['Buy_MABounce'] = apply_cooldown(df['MABounce_Raw'], cooldown); df['Buy_5MABounce'] = apply_cooldown(df['5MABounce_Raw'], cooldown)
    df['Sell_5MA'] = apply_cooldown(df['Sell_5MA_Raw'], cooldown); df['Sell_KD'] = apply_cooldown(df['Sell_KD_Raw'], cooldown)
    df['Sell_RSI'] = apply_cooldown(df['Sell_RSI_Raw'], cooldown); df['Sell_MACD'] = apply_cooldown(df['Sell_MACD_Raw'], cooldown)
    df['Sell_MA20'] = apply_cooldown(df['Sell_MA20_Raw'], cooldown)
    return df

def draw_gauge(val, max_val, title, color):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=val, number={'suffix': "%", 'font': {'size': 18, 'color': color}},
        title={'text': title, 'font': {'size': 12}},
        gauge={'axis': {'range': [0, max_val], 'tickwidth': 1, 'tickcolor': "darkblue"}, 'bar': {'color': color}, 'bgcolor': "white", 'borderwidth': 2, 'bordercolor': "gray"}
    ))
    fig.update_layout(height=120, margin=dict(l=10, r=10, t=60, b=10))
    return fig

# ==========================================
# 🔄 全域同步函數 
# ==========================================
def sync_global_data(style):
    with st.spinner('📡 正在同步雲端金庫與大盤數據...'):
        twii = load_data("^TWII", days=100)
        vix = load_data("^VIX", days=30)
        
        if not twii.empty:
            twii['SMA_20'] = twii['Close'].rolling(20).mean(); twii['SMA_60'] = twii['Close'].rolling(60).mean()
            tw_last = twii.iloc[-1]; vix_last = vix['Close'].iloc[-1] if not vix.empty else 20
            bias_60 = ((tw_last['Close'] - tw_last['SMA_60']) / tw_last['SMA_60']) * 100
            bias_20 = ((tw_last['Close'] - tw_last['SMA_20']) / tw_last['SMA_20']) * 100

            if "順勢" in style:
                s_trend = float(np.clip(40 * (bias_60 + 5) / 10, 0, 40)); s_mom = float(np.clip(20 * (bias_20 + 3) / 6, 0, 20))
                s_bias = float(np.clip(20 - (20 * (bias_20 + 5) / 10), 0, 20)); s_vix = float(np.clip(20 - (20 * (vix_last - 15) / 20), 0, 20))
                titles = ["季線趨勢 (40%)", "月線動能 (20%)", "乖離過熱度 (20%)", "VIX 安全度 (20%)"]
            else:
                s_trend = float(np.clip(40 * (-bias_60 + 5) / 10, 0, 40)); s_mom = float(np.clip(20 * (-bias_20 + 3) / 6, 0, 20))
                s_bias = float(np.clip(20 * (-bias_20 + 5) / 10, 0, 20)); s_vix = float(np.clip(20 * (vix_last - 15) / 20, 0, 20))
                titles = ["季線跌深度 (40%)", "月線超賣度 (20%)", "負乖離價值 (20%)", "VIX 恐慌度 (20%)"]

            st.session_state.market_scores = {'trend': round(s_trend, 1), 'mom': round(s_mom, 1), 'bias': round(s_bias, 1), 'vix': round(s_vix, 1), 'total': round(s_trend + s_mom + s_bias + s_vix, 1), 'titles': titles}
        
        all_holdings = pd.DataFrame(sh.worksheet("Holdings").get_all_records())
        if not all_holdings.empty and 'Username' in all_holdings.columns:
            uh = all_holdings[all_holdings['Username'] == st.session_state["username"]].copy()
            uh['目前股價'] = uh['Entry_Price']; uh['目前市值'] = uh['Total_Cost']; uh['未實現損益 (%)'] = 0.0
            total_mkt_val = 0
            for idx, row in uh.iterrows():
                try:
                    hist = yf.Ticker(row['Ticker']).history(period="5d")
                    if not hist.empty:
                        curr_p = float(hist['Close'].iloc[-1]); mkt_val = curr_p * row['Shares']
                        uh.at[idx, '目前股價'] = round(curr_p, 2); uh.at[idx, '目前市值'] = round(mkt_val, 0)
                        uh.at[idx, '未實現損益 (%)'] = round(((curr_p - row['Entry_Price']) / row['Entry_Price']) * 100, 2)
                        total_mkt_val += mkt_val
                    else: total_mkt_val += row['Total_Cost']
                except: total_mkt_val += row['Total_Cost']
            st.session_state.user_holdings = uh; st.session_state.total_mkt_val = total_mkt_val
        else:
            st.session_state.user_holdings = pd.DataFrame(); st.session_state.total_mkt_val = 0
        st.session_state.market_fetched = True

# ==========================================
# ⚙️ 左側邊欄設定 (★ 完美修復文字與符號)
# ==========================================
st.sidebar.title(f"👤 歡迎回來，{st.session_state['username']}！")
st.sidebar.metric("🏦 雲端可用現金", f"${st.session_state['cash_balance']:,.0f}")
if st.sidebar.button("登出系統"): st.session_state["logged_in"] = False; st.rerun()

st.sidebar.markdown("---")
st.sidebar.title("🧠 核心交易流派選擇")
trade_style = st.sidebar.radio("請選擇您的操作信仰：", ["📈 順勢動能 (右側交易)", "🛒 價值抄底 (左側交易)"])

if st.sidebar.button("🔄 同步雲端大盤與帳本", type="primary", use_container_width=True):
    sync_global_data(trade_style)

if not st.session_state.market_fetched: sync_global_data(trade_style)

st.sidebar.markdown("---")
sidebar_trade_container = st.sidebar.container()
st.sidebar.markdown("---")

st.sidebar.title("⚙️ 策略參數控制台")
show_trade_lines = st.sidebar.checkbox("開啟【買賣區間透視方塊】(圖表顯示報酬)", value=True)
use_adx_filter = st.sidebar.checkbox("開啟【ADX 趨勢過濾】(過濾盤整雜訊)", value=True)
cooldown_days = st.sidebar.slider("訊號冷卻天數 (建議：5天)", 1, 10, 5)
safe_bias_limit = st.sidebar.slider("進場安全乖離率上限 (%) (建議：5.0)", 1.0, 15.0, 5.0)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 買點設定 (向上箭頭 ▲)")
use_breakout = st.sidebar.checkbox("開啟【壓縮突破】買點 (桃紅 ▲)", value=True)
bbw_factor = st.sidebar.slider("└ 布林壓縮容錯率", 1.0, 1.5, 1.1)
vol_factor = st.sidebar.slider("└ 成交量爆發倍數", 1.0, 3.0, 1.5)
use_pullback = st.sidebar.checkbox("開啟【多頭拉回】買點 (綠色 ▲)", value=False)
kd_threshold = st.sidebar.slider("└ KD 金叉最高位階", 20, 80, 50)
use_ma_bounce = st.sidebar.checkbox("開啟【20MA 回踩】波段買點 (淺藍 ▲)", value=True)
use_5ma_bounce = st.sidebar.checkbox("開啟【5MA 回踩】飆股買點 (黃色 ▲)", value=False)

st.sidebar.markdown("---")
st.sidebar.subheader("🛑 賣點設定 (向下箭頭 ▼)")
use_sell_5ma = st.sidebar.checkbox("開啟【跌破 5MA】極短線停利 (紅色 ▼)", value=False)
use_sell_kd = st.sidebar.checkbox("開啟【KD 高檔死叉】短線停利 (橘色 ▼)", value=False)
use_sell_rsi = st.sidebar.checkbox("開啟【RSI 跌破 70】過熱出場 (紫色 ▼)", value=False)
use_sell_macd = st.sidebar.checkbox("開啟【MACD 死叉】波段轉弱 (深藍 ▼)", value=True)
use_sell_ma = st.sidebar.checkbox("開啟【跌破 20MA】波段停損 (黑色 ▼)", value=True)

# ==========================================
# 🗂️ 建立分頁
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["📊 個股分析與配速", "🚀 策略選股掃描器", "💰 策略回測實驗室", "⚖️ 金庫與大盤儀表板"])

# ------------------------------------------
# 分頁一：個股詳細分析 (★ 升級智能動態資金配速器)
# ------------------------------------------
with tab1:
    ticker_input_raw = st.text_input("🔍 請輸入要分析的股票代碼", value="2330.TW")
    ticker_input = ticker_input_raw.strip().upper()
    df_raw = load_data(ticker_input, days=1825) 
    
    if not df_raw.empty:
        stock_name = get_stock_name(ticker_input)
        st.markdown(f"## 📊 {stock_name} ({ticker_input})")
        df = calculate_indicators(df_raw.copy(), bbw_factor, vol_factor, kd_threshold, use_adx_filter, cooldown_days, safe_bias_limit)
        latest, prev = df.iloc[-1], df.iloc[-2]
        
        # ==========================================
        # ★ AI 智能資金配速器 (Dynamic Pacing)
        # ==========================================
        st.markdown(f"### 🧮 智能資金配速與建倉計算機 ({'📈 順勢動能' if '順勢' in trade_style else '🛒 價值抄底'}模型)")
        
        total_equity = st.session_state["cash_balance"] + st.session_state.total_mkt_val
        target_pct = st.session_state.market_scores['total'] / 100.0
        current_pct = st.session_state.total_mkt_val / total_equity if total_equity > 0 else 0
        gap_pct = target_pct - current_pct
        gap_amt = total_equity * gap_pct

        if gap_amt <= 0:
            st.error(f"🚨 **資金水位已滿！** 目前庫存 {current_pct*100:.1f}% 已達大盤建議水位 {target_pct*100:.1f}%。建議今日【調節減碼】，不宜建倉！")
            recommended_shares = 0
        else:
            st.info(f"💡 **目前總資金缺口：** 距離大盤滿水位還有 **{gap_pct*100:.1f}%** 空間，可動用總預算約 **${gap_amt:,.0f}**。")
            
            # --- 系統自動判斷建倉天數 ---
            status = latest['Status_Signal']
            rsi = latest['RSI']
            entry_price = latest['Close']
            
            if "順勢" in trade_style:
                if "極度危險" in status: pacing_days = 10; pacing_reason = "🔴 個股處於極度危險過熱區，強烈建議放緩建倉節奏 (分為 10 天投入)。"
                elif "留意拉回" in status: pacing_days = 5; pacing_reason = "🟡 個股動能偏高，有拉回風險，建議適度分散 (分為 5 天投入)。"
                elif "安全區間" in status: pacing_days = 2; pacing_reason = "🟢 個股處於安全起漲區，動能良好，建議加速建倉 (分為 2 天投入)。"
                else: pacing_days = 5; pacing_reason = "⚫ 趨勢偏弱，保守配速 (分為 5 天投入)。"
            else: # 價值模式
                if rsi < 30 or entry_price < latest['Lower_Band']: pacing_days = 1; pacing_reason = "🔴 極度恐慌區！價值嚴重低估，建議「一波重壓」(1 天內打滿預算)！"
                elif rsi < 40 or entry_price < latest['SMA_60']: pacing_days = 3; pacing_reason = "🟡 跌深反彈區，價值浮現，建議「積極分批」(分為 3 天投入)。"
                else: pacing_days = 5; pacing_reason = "🟢 未達極度恐慌標準，建議「保守試水溫」(分為 5 天投入)。"

            st.markdown(f"#### ⏱️ 系統智能配速判定：**今日起分為 {pacing_days} 天建倉**")
            st.caption(f"🤖 判定邏輯：{pacing_reason}")
            
            col_p2, col_p3 = st.columns(2)
            with col_p2:
                num_stocks_today = st.slider("🛒 今日預計總共買進幾檔股票？", 1, 10, 2, help="系統會將今天的配速額度，平均分給您預計買進的檔數。")
            with col_p3:
                risk_pct = st.slider("⚠️ 單筆最大虧損容忍度 (%)", 0.5, 5.0, 2.0, 0.5)

            # 精算單檔預算
            today_budget = gap_amt / pacing_days
            per_stock_budget = today_budget / num_stocks_today
            shares_by_budget = int(per_stock_budget // entry_price)

            risk_amount = total_equity * (risk_pct / 100.0)
            if "順勢" in trade_style:
                stop_loss_price = latest['SMA_20']
                if entry_price > stop_loss_price:
                    risk_per_share = entry_price - stop_loss_price
                    shares_by_risk = int(risk_amount // risk_per_share)
                    recommended_shares = min(shares_by_budget, shares_by_risk)
                    st.success(f"🎯 **結合配速與風險，單檔建議買進： {recommended_shares:,.0f} 股** (單檔預算上限: ${per_stock_budget:,.0f})")
                else: 
                    st.warning("🚨 股價低於 20MA，順勢防守機制啟動，建議：【空手觀望，0 股】！")
                    recommended_shares = 0
            else:
                assumed_risk = entry_price * 0.10 
                shares_by_risk = int(risk_amount // assumed_risk)
                max_shares = min(shares_by_budget, shares_by_risk)
                
                if entry_price > latest['SMA_20']:
                    st.warning("⚖️ 股價在月線之上，無特價空間。建議：【耐心等待回檔，0 股】")
                    recommended_shares = 0
                else:
                    weight = 1.0 if pacing_days == 1 else (0.5 if pacing_days == 3 else 0.2)
                    recommended_shares = int(max_shares * weight)
                    st.success(f"🛒 **左側抄底模型** -> 結合配速，建議買進： **{recommended_shares:,.0f} 股**")
                    st.caption(f"單檔預算 ${per_stock_budget:,.0f} x 左側權重 {weight*100}% = 本次動用 ${recommended_shares * entry_price:,.0f}")
            
        st.markdown("---")

        with sidebar_trade_container:
            st.markdown("### ✍️ 專屬下單匣")
            with st.form("manual_trade_form"):
                manual_ticker = st.text_input("股票代碼", value=ticker_input)
                manual_shares = st.number_input("買進股數", min_value=1, value=max(1, int(recommended_shares)))
                manual_price = st.number_input("成交單價", min_value=0.01, value=float(latest['Close']), format="%.2f")
                if st.form_submit_button("🚀 寫入雲端金庫", type="primary", use_container_width=True):
                    actual_cost = manual_shares * manual_price
                    if actual_cost > st.session_state['cash_balance']: st.error(f"🚨 餘額不足！")
                    else:
                        sh.worksheet("Holdings").append_row([st.session_state["username"], manual_ticker.upper(), manual_shares, manual_price, actual_cost, datetime.datetime.now().strftime("%Y-%m-%d")])
                        new_cash = st.session_state['cash_balance'] - actual_cost
                        ws_users = sh.worksheet("Users")
                        df_users = pd.DataFrame(ws_users.get_all_records())
                        row_idx = df_users.index[df_users['Username'] == st.session_state["username"]].tolist()[0] + 2 
                        ws_users.update_cell(row_idx, 4, new_cash)
                        st.session_state["cash_balance"] = new_cash
                        st.success(f"✅ 已買進 {manual_ticker.upper()}！")
                        st.rerun()

        # 戰情室與圖表繪製
        st.markdown(f"### 🛡️ 今日戰情室：進場風險評估 (日期: {latest.name.strftime('%Y-%m-%d')})")
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("最新收盤價", f"{latest['Close']:.2f}", f"{(latest['Close'] - prev['Close']):.2f} ({((latest['Close'] - prev['Close']) / prev['Close']) * 100:.2f}%)")
        with col2: st.metric("與 20MA 乖離率", f"{latest['Bias_20MA']:.2f}%")
        with col3: st.metric("RSI (14)", f"{latest['RSI']:.1f}")
        with col4: st.markdown(f"**判定**<br><span style='font-size:20px'>{latest['Status_Signal']}</span>", unsafe_allow_html=True)
        st.markdown("---")
        
        fig = make_subplots(rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.4, 0.12, 0.12, 0.12, 0.12, 0.12], subplot_titles=("K線與均線", "成交量", "KD", "MACD", "RSI", "OBV"))
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', customdata=df['Hover_Text'], hovertemplate="%{customdata}<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='rgba(150,150,150,0.5)', width=1, dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='magenta', width=1.5)), row=1, col=1) 
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], line=dict(color='green', width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='rgba(150,150,150,0.5)', width=1, dash='dash')), row=1, col=1)

        if use_breakout: fig.add_trace(go.Scatter(x=df[df['Buy_Breakout']].index, y=df.loc[df['Buy_Breakout'], 'Low'] - df.loc[df['Buy_Breakout'], 'ATR_14']*0.4, mode='markers', marker=dict(symbol='triangle-up', size=14, color='magenta', line=dict(width=1, color='black'))), row=1, col=1)
        if use_pullback: fig.add_trace(go.Scatter(x=df[df['Buy_Pullback']].index, y=df.loc[df['Buy_Pullback'], 'Low'] - df.loc[df['Buy_Pullback'], 'ATR_14']*0.8, mode='markers', marker=dict(symbol='triangle-up', size=13, color='lime', line=dict(width=1, color='black'))), row=1, col=1)
        if use_ma_bounce: fig.add_trace(go.Scatter(x=df[df['Buy_MABounce']].index, y=df.loc[df['Buy_MABounce'], 'Low'] - df.loc[df['Buy_MABounce'], 'ATR_14']*1.2, mode='markers', marker=dict(symbol='triangle-up', size=13, color='dodgerblue', line=dict(width=1, color='black'))), row=1, col=1)
        if use_5ma_bounce: fig.add_trace(go.Scatter(x=df[df['Buy_5MABounce']].index, y=df.loc[df['Buy_5MABounce'], 'Low'] - df.loc[df['Buy_5MABounce'], 'ATR_14']*1.6, mode='markers', marker=dict(symbol='triangle-up', size=12, color='gold', line=dict(width=1, color='black'))), row=1, col=1)
        if use_sell_5ma: fig.add_trace(go.Scatter(x=df[df['Sell_5MA']].index, y=df.loc[df['Sell_5MA'], 'High'] + df.loc[df['Sell_5MA'], 'ATR_14']*0.4, mode='markers', marker=dict(symbol='triangle-down', size=12, color='red', line=dict(width=1, color='black'))), row=1, col=1)
        if use_sell_macd: fig.add_trace(go.Scatter(x=df[df['Sell_MACD']].index, y=df.loc[df['Sell_MACD'], 'High'] + df.loc[df['Sell_MACD'], 'ATR_14']*1.6, mode='markers', marker=dict(symbol='triangle-down', size=12, color='blue', line=dict(width=1, color='black'))), row=1, col=1)
        if use_sell_ma: fig.add_trace(go.Scatter(x=df[df['Sell_MA20']].index, y=df.loc[df['Sell_MA20'], 'High'] + df.loc[df['Sell_MA20'], 'ATR_14']*2.0, mode='markers', marker=dict(symbol='triangle-down', size=13, color='black', line=dict(width=1, color='black'))), row=1, col=1)

        if show_trade_lines:
            df['CBuy'] = df['Buy_Breakout'] | df['Buy_Pullback'] | df['Buy_MABounce'] | df['Buy_5MABounce']
            df['CSell'] = df['Sell_5MA'] | df['Sell_KD'] | df['Sell_RSI'] | df['Sell_MACD'] | df['Sell_MA20']
            pos, ep, ed = 0, 0, None
            for i in range(len(df)):
                if pos == 0 and df['CBuy'].iloc[i]: pos, ep, ed = 1, df['Close'].iloc[i], df.index[i]
                elif pos == 1 and df['CSell'].iloc[i]:
                    pos, xp = 0, df['Close'].iloc[i]
                    ret = (xp - ep)/ep * 100
                    lc, fc, bg = ("rgba(0,200,0,0.8)", "rgba(0,200,0,0.15)", "green") if ret > 0 else ("rgba(255,0,0,0.8)", "rgba(255,0,0,0.15)", "red")
                    fig.add_shape(type="rect", x0=ed, y0=ep, x1=df.index[i], y1=xp, fillcolor=fc, line=dict(color=lc, width=2), row=1, col=1)
                    fig.add_annotation(x=df.index[i], y=df['High'].iloc[i] + df['ATR_14'].iloc[i]*2.8, text=f"<b>{xp-ep:.2f} ({ret:.1f}%)</b>", showarrow=True, arrowhead=1, arrowcolor=lc, ax=0, ay=-30, font=dict(color="white", size=11), bgcolor=bg, row=1, col=1)

        vol_colors = ['red' if c >= o else 'green' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=vol_colors), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Vol_5MA'], line=dict(color='orange', dash='dot')), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], line=dict(color='blue')), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], line=dict(color='orange')), row=3, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df['Histogram'], marker_color=['red' if v > 0 else 'green' for v in df['Histogram']]), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='orange')), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Signal'], line=dict(color='purple')), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='darkred')), row=5, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], line=dict(color='teal')), row=6, col=1)
        fig.update_layout(height=1300, hovermode="x unified", dragmode='pan', showlegend=False, xaxis_rangeslider_visible=False)
        dt_breaks = [d.strftime("%Y-%m-%d") for d in pd.date_range(start=df.index[0], end=df.index[-1]) if d not in df.index]
        fig.update_xaxes(range=[df.index[-1] - pd.Timedelta(days=150), df.index[-1] + pd.Timedelta(days=10)], rangebreaks=[dict(values=dt_breaks)])
        st.plotly_chart(fig, use_container_width=True)

with tab2: st.info("🚀 掃描器運作中...")
with tab3: st.info("💰 回測實驗室運作中...")

# ------------------------------------------
# 分頁四：⚖️ 雲端金庫與大盤儀表板 
# ------------------------------------------
with tab4:
    st.header("⚖️ 雲端專屬金庫 ＆ 戰情儀表板")
    if st.session_state.market_fetched:
        st.markdown(f"### 🌦️ 大盤氣象台 ({'順勢多頭防守' if '順勢' in trade_style else '逆勢價值抄底'}模型)")
        ms = st.session_state.market_scores
        def get_color(val, max_val): return "limegreen" if val >= max_val * 0.8 else ("crimson" if val <= max_val * 0.4 else "gold")
        col_g1, col_g2, col_g3, col_g4 = st.columns(4)
        with col_g1: st.plotly_chart(draw_gauge(ms['trend'], 40, ms['titles'][0], get_color(ms['trend'], 40)), use_container_width=True)
        with col_g2: st.plotly_chart(draw_gauge(ms['mom'], 20, ms['titles'][1], get_color(ms['mom'], 20)), use_container_width=True)
        with col_g3: st.plotly_chart(draw_gauge(ms['bias'], 20, ms['titles'][2], get_color(ms['bias'], 20)), use_container_width=True)
        with col_g4: st.plotly_chart(draw_gauge(ms['vix'], 20, ms['titles'][3], get_color(ms['vix'], 20)), use_container_width=True)
        
        total_equity = st.session_state["cash_balance"] + st.session_state.total_mkt_val
        current_pct = (st.session_state.total_mkt_val / total_equity) * 100 if total_equity > 0 else 0
        
        st.markdown("### ⚖️ 資金水位再平衡建議")
        col_r1, col_r2, col_r3 = st.columns(3)
        col_r1.metric("總資產淨值 (現金+股票)", f"${total_equity:,.0f}")
        col_r2.metric("目前持股水位", f"{current_pct:.1f}%")
        col_r3.metric("🎯 系統動態建議水位", f"{ms['total']}%")
        st.markdown("---")
        
        st.markdown("### 💼 我的雲端庫存清單")
        df_h = st.session_state.user_holdings
        if not df_h.empty:
            view_mode = st.radio("👀 檢視模式：", ["📊 彙總視角", "📝 明細視角"], horizontal=True)
            if "彙總" in view_mode:
                summary = df_h.groupby('Ticker').agg({'Shares': 'sum', 'Total_Cost': 'sum', '目前股價': 'first'}).reset_index()
                summary['平均成本'] = (summary['Total_Cost'] / summary['Shares']).round(2)
                summary['目前市值'] = (summary['Shares'] * summary['目前股價']).round(0)
                summary['未實現損益 (%)'] = (((summary['目前股價'] - summary['平均成本']) / summary['平均成本']) * 100).round(2)
                st.dataframe(summary[['Ticker', 'Shares', '平均成本', '目前股價', 'Total_Cost', '目前市值', '未實現損益 (%)']], use_container_width=True)
                csv_data = summary.to_csv(index=False).encode('utf-8-sig')
            else:
                st.dataframe(df_h[['Ticker', 'Shares', 'Entry_Price', '目前股價', 'Total_Cost', '目前市值', '未實現損益 (%)', 'Buy_Date']], use_container_width=True)
                csv_data = df_h.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 匯出 Excel (CSV)", data=csv_data, file_name="Portfolio.csv", mime="text/csv", type="primary")
        else: st.warning("目前雲端金庫空空如也，請至左側下單匣建倉！")
    else: st.info("請點擊左側邊欄的「🔄 同步雲端大盤與帳本」以載入金庫數據！")
