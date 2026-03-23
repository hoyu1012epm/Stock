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
st.set_page_config(page_title="專屬量化操盤副駕 | 雲端金庫版", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# ☁️ 雲端資料庫連線設定 (Google Sheets)
# ==========================================
@st.cache_resource(ttl=3600)
def init_connection():
    try:
        # 終極防禦：加入 strict=False，強迫系統讀懂包含換行符號的密碼
        raw_json = st.secrets["GOOGLE_JSON"]
        creds_json = json.loads(raw_json, strict=False) 
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        client = gspread.authorize(creds)
        sh = client.open("Stock_Database")
        
        # 自動建立/確認資料表
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
# 🔐 登入與註冊系統
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.update({"logged_in": False, "username": "", "cash_balance": 0.0, "market_fetched": False})

if not st.session_state["logged_in"]:
    st.title("🔐 專屬量化操盤副駕 - 登入系統")
    tab_login, tab_signup = st.tabs(["登入", "註冊新帳號"])
    
    with tab_login:
        st.subheader("使用者登入")
        login_user = st.text_input("帳號 (Username)", key="log_user")
        login_pwd = st.text_input("密碼 (Password)", type="password", key="log_pwd")
        if st.button("登入系統", type="primary"):
            if sh:
                ws_users = sh.worksheet("Users")
                users_data = ws_users.get_all_records()
                df_users = pd.DataFrame(users_data)
                
                if not df_users.empty and login_user in df_users["Username"].values:
                    user_row = df_users[df_users["Username"] == login_user].iloc[0]
                    if str(user_row["Password"]) == login_pwd:
                        st.session_state.update({"logged_in": True, "username": login_user, "cash_balance": float(user_row["Cash_Balance"])})
                        st.rerun()
                    else: st.error("密碼錯誤！")
                else: st.error("找不到此帳號，請先註冊！")

    with tab_signup:
        st.subheader("建立專屬雲端金庫")
        sign_user = st.text_input("設定帳號 (Username)", key="sig_user")
        sign_pwd = st.text_input("設定密碼 (Password)", type="password", key="sig_pwd")
        init_cap = st.number_input("初始投資本金 (NTD)", min_value=10000, value=1000000, step=10000)
        if st.button("註冊並建立帳本"):
            if sh and sign_user and sign_pwd:
                ws_users = sh.worksheet("Users")
                users_data = ws_users.get_all_records()
                df_users = pd.DataFrame(users_data) if users_data else pd.DataFrame(columns=["Username"])
                
                if sign_user in df_users["Username"].values: st.error("此帳號已被使用，請換一個！")
                else:
                    ws_users.append_row([sign_user, sign_pwd, init_cap, init_cap])
                    st.success("🎉 註冊成功！請切換到「登入」分頁進入系統。")
    st.stop() 

# ==========================================
# ⚙️ 登入後主程式開始
# ==========================================
# 左側選單：使用者資訊
st.sidebar.title(f"👤 歡迎回來，{st.session_state['username']}！")
st.sidebar.metric("🏦 雲端可用現金", f"${st.session_state['cash_balance']:,.0f}")
if st.sidebar.button("登出系統"):
    st.session_state["logged_in"] = False
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.title("⚙️ 策略參數控制台")
show_trade_lines = st.sidebar.checkbox("開啟【買賣區間透視方塊】(圖表顯示報酬)", value=True)
use_adx_filter = st.sidebar.checkbox("開啟【ADX 趨勢過濾】(過濾盤整雜訊)", value=True)
cooldown_days = st.sidebar.slider("訊號冷卻天數 (建議：5 天)", min_value=1, max_value=10, value=5, step=1)
safe_bias_limit = st.sidebar.slider("進場安全乖離率上限 (建議：5.0 %)", min_value=1.0, max_value=15.0, value=5.0, step=0.5)

st.sidebar.markdown("---")

st.sidebar.subheader("🎯 買點設定 (向上箭頭 ▲)")
use_breakout = st.sidebar.checkbox("開啟【壓縮突破】買點 (桃紅 ▲)", value=True)
bbw_factor = st.sidebar.slider("└ 布林壓縮容錯率", min_value=1.0, max_value=1.5, value=1.1, step=0.05)
vol_factor = st.sidebar.slider("└ 成交量爆發倍數", min_value=1.0, max_value=3.0, value=1.5, step=0.1)
use_pullback = st.sidebar.checkbox("開啟【多頭拉回】買點 (綠色 ▲)", value=False)
kd_threshold = st.sidebar.slider("└ KD 金叉最高位階", min_value=20, max_value=80, value=50, step=5)
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
# 📊 核心運算函數
# ==========================================
@st.cache_data(ttl=86400)
def get_stock_name(ticker):
    try:
        info = yf.Ticker(ticker).info
        return info.get('shortName', info.get('longName', ticker))
    except: return ticker

@st.cache_data(ttl=3600)
def load_data(ticker, days=1825): 
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=days)
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    if df.empty: return df
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df

def apply_cooldown(signal_series, cooldown_period):
    clean_signal = pd.Series(False, index=signal_series.index)
    last_signal_idx = -cooldown_period - 1
    for i, val in enumerate(signal_series):
        if val and (i - last_signal_idx) > cooldown_period:
            clean_signal.iloc[i] = True
            last_signal_idx = i
    return clean_signal

def calculate_indicators_and_signals(df, bbw_f, vol_f, kd_thresh, use_adx, cooldown, bias_limit):
    if len(df) < 60: return df 
    df['SMA_5'] = df['Close'].rolling(window=5).mean()
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_60'] = df['Close'].rolling(window=60).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
    df['Upper_Band'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['Lower_Band'] = df['SMA_20'] - (df['STD_20'] * 2)
    df['BBW'] = (df['Upper_Band'] - df['Lower_Band']) / df['SMA_20']
    
    df['EMA_12'] = df['Close'].ewm(span=12, adjust=False).mean()
    df['EMA_26'] = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA_12'] - df['EMA_26']
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Histogram'] = df['MACD'] - df['Signal']
    
    df['9MA_Max'] = df['High'].rolling(window=9).max()
    df['9MA_Min'] = df['Low'].rolling(window=9).min()
    df['RSV'] = (df['Close'] - df['9MA_Min']) / (df['9MA_Max'] - df['9MA_Min']) * 100
    df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
    df['D'] = df['K'].ewm(com=2, adjust=False).mean()
    
    delta = df['Close'].diff()
    up = delta.clip(lower=0); down = -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + rs))
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
    df['Bias_20MA'] = (df['Close'] - df['SMA_20']) / df['SMA_20'] * 100
    
    conditions = [(df['RSI'] >= 70) | (df['Bias_20MA'] >= bias_limit), (df['RSI'] >= 60) | (df['Bias_20MA'] >= (bias_limit * 0.7)), (df['Close'] < df['SMA_60'])]
    choices = ["🔴 極度危險 (勿追高)", "🟡 留意拉回風險", "⚫ 空頭趨勢 (不建議)"]
    df['Status_Signal'] = np.select(conditions, choices, default="🟢 安全區間 (可佈局)")
    df['Hover_Text'] = ("20MA乖離率: " + df['Bias_20MA'].round(2).astype(str) + "%<br>RSI (14): " + df['RSI'].round(1).astype(str) + "<br>進場判定: <b>" + df['Status_Signal'] + "</b>")
    
    df['Prev_Close'] = df['Close'].shift(1)
    df['TR'] = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Prev_Close']), abs(df['Low'] - df['Prev_Close'])))
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']), np.maximum(df['High'] - df['High'].shift(1), 0), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)), np.maximum(df['Low'].shift(1) - df['Low'], 0), 0)
    df['ATR_14'] = df['TR'].ewm(alpha=1/14, adjust=False).mean()
    
    df['+DI'] = 100 * (df['+DM'].ewm(alpha=1/14, adjust=False).mean() / df['ATR_14'])
    df['-DI'] = 100 * (df['-DM'].ewm(alpha=1/14, adjust=False).mean() / df['ATR_14'])
    df['DX'] = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = df['DX'].ewm(alpha=1/14, adjust=False).mean()
    adx_condition = (df['ADX'] > 20) if use_adx else True

    df['Vol_5MA'] = df['Volume'].rolling(window=5).mean()
    df['Is_Squeeze'] = df['BBW'] <= df['BBW'].rolling(window=20).min() * bbw_f
    df['Breakout_Raw'] = (df['Is_Squeeze'].rolling(window=5).max().fillna(0) == 1) & (df['Close'] > df['Upper_Band']) & (df['Volume'] > df['Vol_5MA'] * vol_f) & (df['Close'] > df['SMA_60']) & adx_condition
    df['Pullback_Raw'] = (df['K'] > df['D']) & (df['K'].shift(1) <= df['D'].shift(1)) & (df['K'] <= kd_thresh) & (df['Close'] > df['SMA_60']) & adx_condition
    df['MABounce_Raw'] = (df['SMA_5'] > df['SMA_20']) & (df['SMA_20'] > df['SMA_60']) & (df['Low'] <= (df['SMA_20'] * 1.015)) & (df['Close'] > df['SMA_20']) & (df['Close'] > df['Open']) & adx_condition
    df['5MABounce_Raw'] = (df['SMA_5'] > df['SMA_20']) & (df['Close'] > df['SMA_20']) & (df['Low'] <= (df['SMA_5'] * 1.015)) & (df['Close'] > df['SMA_5']) & (df['Close'] > df['Open']) & adx_condition

    df['Sell_5MA_Raw'] = (df['Close'] < df['SMA_5']) & (df['Close'].shift(1) >= df['SMA_5'].shift(1))
    df['Sell_KD_Raw'] = (df['K'] < df['D']) & (df['K'].shift(1) >= df['D'].shift(1)) & (df['K'].shift(1) >= 80)
    df['Sell_RSI_Raw'] = (df['RSI'] < 70) & (df['RSI'].shift(1) >= 70)
    df['Sell_MACD_Raw'] = (df['MACD'] < df['Signal']) & (df['MACD'].shift(1) >= df['Signal'].shift(1))
    df['Sell_MA20_Raw'] = (df['Close'] < df['SMA_20']) & (df['Close'].shift(1) >= df['SMA_20'].shift(1))

    df['Buy_Breakout'] = apply_cooldown(df['Breakout_Raw'], cooldown)
    df['Buy_Pullback'] = apply_cooldown(df['Pullback_Raw'], cooldown)
    df['Buy_MABounce'] = apply_cooldown(df['MABounce_Raw'], cooldown)
    df['Buy_5MABounce'] = apply_cooldown(df['5MABounce_Raw'], cooldown)
    
    df['Sell_5MA'] = apply_cooldown(df['Sell_5MA_Raw'], cooldown)
    df['Sell_KD'] = apply_cooldown(df['Sell_KD_Raw'], cooldown)
    df['Sell_RSI'] = apply_cooldown(df['Sell_RSI_Raw'], cooldown)
    df['Sell_MACD'] = apply_cooldown(df['Sell_MACD_Raw'], cooldown)
    df['Sell_MA20'] = apply_cooldown(df['Sell_MA20_Raw'], cooldown)
    return df

# ==========================================
# ★ 修復與優化：迷你儀表板圖表產生器
# ==========================================
def draw_gauge(val, max_val, title, color):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=val, 
        number={'suffix': "%", 'font': {'size': 18, 'color': color}},
        title={'text': title, 'font': {'size': 12}},
        gauge={'axis': {'range': [0, max_val], 'tickwidth': 1, 'tickcolor': "darkblue"},
               'bar': {'color': color}, 'bgcolor': "white", 'borderwidth': 2, 'bordercolor': "gray"}
    ))
    # ★ 修復的核心：增加頂部邊距 (t=60)，並顯著縮小高度 (height=120)
    fig.update_layout(height=120, margin=dict(l=10, r=10, t=60, b=10))
    return fig

# ==========================================
# 🗂️ 建立分頁
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["📊 個股詳細分析", "🚀 策略選股掃描器", "💰 策略回測實驗室", "⚖️ 雲端金庫與再平衡"])

# ------------------------------------------
# 分頁一：個股詳細分析 (包含手動建倉系統)
# ------------------------------------------
with tab1:
    ticker_input_raw = st.text_input("🔍 請輸入要分析的股票代碼", value="2330.TW", key="tab1_input")
    ticker_input = ticker_input_raw.strip().upper()
    df_raw = load_data(ticker_input, days=1825) 
    
    if not df_raw.empty:
        stock_name = get_stock_name(ticker_input)
        st.markdown(f"## 📊 {stock_name} ({ticker_input})")
        df = calculate_indicators_and_signals(df_raw.copy(), bbw_factor, vol_factor, kd_threshold, use_adx_filter, cooldown_days, safe_bias_limit)
        
        # --- 畫圖方塊獲利邏輯 (略) ---
        if show_trade_lines:
            # 此處保留你原本代碼中的 Combined_Buy, Combined_Sell 與 trades_viz 計算邏輯，為省篇幅略過
            pass

        # --- 系統建議與手動建倉 ---
        latest, prev = df.iloc[-1], df.iloc[-2]
        
        st.markdown("### 🧮 系統建倉建議 (風險平價计算機)")
        col_calc1, col_calc2 = st.columns(2)
        with col_calc1: st.metric("🏦 目前雲端可用資金", f"${st.session_state['cash_balance']:,.0f}")
        with col_calc2: risk_pct = st.slider("⚠️ 單筆願意承受最大虧損 (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)

        total_capital = st.session_state['cash_balance']
        risk_amount = total_capital * (risk_pct / 100.0)
        entry_price = latest['Close']
        stop_loss_price = latest['SMA_20'] # 以 20MA 作為防守線
        recommended_shares = 0

        if entry_price > stop_loss_price and total_capital > 0:
            recommended_shares = min(int(risk_amount // (entry_price - stop_loss_price)), int(total_capital // entry_price))
            st.success(f"📈 **系統建議買進股數： {recommended_shares:,.0f} 股** (動用資金：${recommended_shares * entry_price:,.0f})")
        else: st.error("🚨 目前股價低於防守線 20MA，處於空頭弱勢區。建議：【空手觀望，0 股】！")
            
        st.markdown("---")

        st.markdown("### ✍️ 建立專屬倉位 (交易紀錄)")
        st.caption("請依照您實際在券商軟體成交的數字填寫。本程式僅提供策略參考，賦予您最高決策權。")
        
        with st.form("manual_trade_form"):
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1: manual_ticker = st.text_input("股票代碼", value=ticker_input)
            with col_m2: manual_shares = st.number_input("實際買進股數", min_value=1, value=max(1, int(recommended_shares)))
            with col_m3: manual_price = st.number_input("實際成交單價", min_value=0.01, value=float(latest['Close']), format="%.2f")
            
            submitted = st.form_submit_button("🚀 確認寫入雲端金庫", type="primary")
            
            if submitted:
                actual_cost = manual_shares * manual_price
                if actual_cost > st.session_state['cash_balance']:
                    st.error(f"🚨 餘額不足！需要 ${actual_cost:,.0f}，但金庫只剩 ${st.session_state['cash_balance']:,.0f}")
                else:
                    ws_holdings = sh.worksheet("Holdings")
                    ws_users = sh.worksheet("Users")
                    
                    buy_date = datetime.datetime.now().strftime("%Y-%m-%d")
                    ws_holdings.append_row([st.session_state["username"], manual_ticker.upper(), manual_shares, manual_price, actual_cost, buy_date])
                    
                    new_cash = st.session_state['cash_balance'] - actual_cost
                    users_data = ws_users.get_all_records()
                    df_users = pd.DataFrame(users_data)
                    row_idx = df_users.index[df_users['Username'] == st.session_state["username"]].tolist()[0] + 2 
                    ws_users.update_cell(row_idx, 4, new_cash)
                    
                    st.session_state["cash_balance"] = new_cash
                    st.success(f"✅ 成功手動買進 {manual_ticker.upper()} 共 {manual_shares} 股！請前往【雲端金庫】查看。")
                    st.rerun()

        st.markdown("---")
        
        # K線與指標畫圖區塊 (維持原樣)
        fig = make_subplots(rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.4, 0.12, 0.12, 0.12, 0.12, 0.12], subplot_titles=("K線與均線", "成交量", "KD", "MACD", "RSI", "OBV"))
        # 此處保留你原本代碼中的 fig.add_trace 與 fig.update_layout 邏輯，為省篇幅略過
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

with tab2: st.info("掃描器運做中... (維持原樣)")
with tab3: st.info("回測實驗室運作中... (維持原樣)")

# ------------------------------------------
# 分頁四：⚖️ 雲端金庫與迷你大盤儀表板 (視覺修復版)
# ------------------------------------------
with tab4:
    st.header("⚖️ 雲端專屬金庫 ＆ 戰情儀表板")
    st.markdown("系統自動讀取你的庫存，並根據台股大盤四大線性指標判斷你目前的資金水位。")
    
    if st.button("🔄 刷新雲端帳本與大盤數據", type="primary"):
        with st.spinner('正在分析大盤四大線性指標與雲端金庫...'):
            # 1. 抓取大盤數據
            twii = load_data("^TWII", days=100)
            vix = load_data("^VIX", days=30)
            
            if not twii.empty:
                twii['SMA_20'] = twii['Close'].rolling(window=20).mean()
                twii['SMA_60'] = twii['Close'].rolling(window=60).mean()
                tw_last = twii.iloc[-1]
                vix_last = vix['Close'].iloc[-1] if not vix.empty else 20
                
                # ★ 超硬核線性演算法，精準到小數點第一位
                # 1. 季線趨勢 (Max 40): 依據季線乖離率 -5% ~ +5% 線性給分
                bias_60 = ((tw_last['Close'] - tw_last['SMA_60']) / tw_last['SMA_60']) * 100
                s_trend = float(np.clip(40 * (bias_60 + 5) / 10, 0, 40))
                
                # 2. 月線動能 (Max 20): 依據月線乖離率 -3% ~ +3% 線性給分
                bias_20 = ((tw_last['Close'] - tw_last['SMA_20']) / tw_last['SMA_20']) * 100
                s_mom = float(np.clip(20 * (bias_20 + 3) / 6, 0, 20))
                
                # 3. 乖離過熱度 (Max 20): 依據月線乖離率 -5% ~ +5% 反向線性給分 (過熱扣分)
                s_bias = float(np.clip(20 - (20 * (bias_20 + 5) / 10), 0, 20))
                
                # 4. VIX 恐慌情緒 (Max 20): VIX 指數 15 ~ 35 反向線性給分 (恐慌扣分)
                s_vix = float(np.clip(20 - (20 * (vix_last - 15) / 20), 0, 20))
                
                # 總評分 (滿分 100%)
                total_score = round(s_trend + s_mom + s_bias + s_vix, 1)
                
                st.session_state.market_scores = {
                    'trend': round(s_trend, 1), 'mom': round(s_mom, 1), 
                    'bias': round(s_bias, 1), 'vix': round(s_vix, 1), 
                    'total': total_score
                }
            
            # 2. 抓取庫存與計算
            ws_holdings = sh.worksheet("Holdings")
            all_holdings = pd.DataFrame(ws_holdings.get_all_records())
            
            if not all_holdings.empty and 'Username' in all_holdings.columns:
                uh = all_holdings[all_holdings['Username'] == st.session_state["username"]].copy()
                # 防禦升級，確保網路斷線時不會當機
                uh['目前股價'] = uh['Entry_Price']; uh['目前市值'] = uh['Total_Cost']; uh['未實現損益 (%)'] = 0.0
                total_mkt_val = 0
                for idx, row in uh.iterrows():
                    try:
                        hist = yf.Ticker(row['Ticker']).history(period="5d")
                        if not hist.empty:
                            curr_p = float(hist['Close'].iloc[-1])
                            mkt_val = curr_p * row['Shares']
                            uh.at[idx, '目前股價'] = round(curr_p, 2)
                            uh.at[idx, '目前市值'] = round(mkt_val, 0)
                            uh.at[idx, '未實現損益 (%)'] = round(((curr_p - row['Entry_Price']) / row['Entry_Price']) * 100, 2)
                            total_mkt_val += mkt_val
                        else: total_mkt_val += row['Total_Cost']
                    except: total_mkt_val += row['Total_Cost']
                
                st.session_state.user_holdings = uh; st.session_state.total_mkt_val = total_mkt_val
            else: st.session_state.user_holdings = pd.DataFrame(); st.session_state.total_mkt_val = 0
            st.session_state.market_fetched = True

    # ================= 顯示儀表板 (戰情中心) =================
    if st.session_state.market_fetched:
        st.markdown("### 🌦️ 大盤戰情儀表板 (動態線性)")
        ms = st.session_state.market_scores
        
        # 繪製 4 個小儀表板，並根據分數判斷顏色
        def get_color(val, max_val):
            if val >= max_val * 0.8: return "limegreen"
            elif val <= max_val * 0.4: return "crimson"
            else: return "gold"

        col_g1, col_g2, col_g3, col_g4 = st.columns(4)
        with col_g1: st.plotly_chart(draw_gauge(ms['trend'], 40, "季線趨勢 (滿分40%)", get_color(ms['trend'], 40)), use_container_width=True)
        with col_g2: st.plotly_chart(draw_gauge(ms['mom'], 20, "月線動能 (滿分20%)", get_color(ms['mom'], 20)), use_container_width=True)
        with col_g3: st.plotly_chart(draw_gauge(ms['bias'], 20, "乖離過熱度 (滿分20%)", get_color(ms['bias'], 20)), use_container_width=True)
        with col_g4: st.plotly_chart(draw_gauge(ms['vix'], 20, "VIX 恐慌指數 (滿分20%)", get_color(ms['vix'], 20)), use_container_width=True)
        
        # 資金水位計算
        total_equity = st.session_state["cash_balance"] + st.session_state.total_mkt_val
        current_pct = (st.session_state.total_mkt_val / total_equity) * 100 if total_equity > 0 else 0
        suggested_pct = ms['total']
        
        st.markdown("### ⚖️ 資金水位再平衡建議")
        col_r1, col_r2, col_r3 = st.columns(3)
        col_r1.metric("總資產淨值 (現金+股票)", f"${total_equity:,.0f}")
        col_r2.metric("目前持股水位", f"{current_pct:.1f}%")
        col_r3.metric("🎯 系統動態建議水位", f"{suggested_pct}%")
        
        diff_pct = current_pct - suggested_pct
        if diff_pct > 5: st.error(f"🚨 **持股過高！** 建議賣出約 ${total_equity * (diff_pct/100):,.0f} 變現。")
        elif diff_pct < -5: st.success(f"🟢 **水位安全！** 還有約 ${total_equity * (-diff_pct/100):,.0f} 的空間可進場。")
        else: st.info("👌 **資金水位完美平衡！**")

        st.markdown("---")
        
        # ================= 庫存彙總 (自動合併同一檔) =================
        st.markdown("### 💼 我的雲端庫存清單 (自動合併彙總)")
        df_h = st.session_state.user_holdings
        
        if not df_h.empty:
            # ★ 視角切換器
            view_mode = st.radio("👀 請選擇檢視模式：", ["📊 彙總視角 (同一檔自動合併、算平均成本)", "📝 明細視角 (逐筆交易紀錄)"], horizontal=True)
            
            if "彙總" in view_mode:
                # 群組彙總計算：Ticker 為關鍵字
                summary = df_h.groupby('Ticker').agg({
                    'Shares': 'sum',
                    'Total_Cost': 'sum',
                    '目前股價': 'first' # 同一檔股票目前市價都一樣
                }).reset_index()
                # 算出合併後的平均成本、目前總市值、總損益%
                summary['平均成本價'] = (summary['Total_Cost'] / summary['Shares']).round(2)
                summary['目前總市值'] = (summary['Shares'] * summary['目前股價']).round(0)
                summary['總未實現損益 (%)'] = (((summary['目前股價'] - summary['平均成本價']) / summary['平均成本價']) * 100).round(2)
                # 重新排序與顯示欄位
                st.dataframe(summary[['Ticker', 'Shares', '平均成本價', '目前股價', 'Total_Cost', '目前總市值', '總未實現損益 (%)']], use_container_width=True)
            else:
                st.dataframe(df_h[['Ticker', 'Shares', 'Entry_Price', '目前股價', 'Total_Cost', '目前市值', '未實現損益 (%)', 'Buy_Date']], use_container_width=True)
        else: st.warning("目前雲端金庫空空如也，趕快去建倉吧！")
