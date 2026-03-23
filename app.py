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
        try:
            ws_users = sh.worksheet("Users")
        except:
            ws_users = sh.add_worksheet(title="Users", rows="100", cols="5")
            ws_users.append_row(["Username", "Password", "Initial_Capital", "Cash_Balance"])
            
        try:
            ws_holdings = sh.worksheet("Holdings")
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
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["cash_balance"] = 0.0

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
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = login_user
                        st.session_state["cash_balance"] = float(user_row["Cash_Balance"])
                        st.rerun()
                    else:
                        st.error("密碼錯誤！")
                else:
                    st.error("找不到此帳號，請先註冊！")

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
                
                if sign_user in df_users["Username"].values:
                    st.error("此帳號已被使用，請換一個！")
                else:
                    ws_users.append_row([sign_user, sign_pwd, init_cap, init_cap])
                    st.success("🎉 註冊成功！請切換到「登入」分頁進入系統。")
    st.stop() 

# ==========================================
# ⚙️ 登入後主程式開始
# ==========================================
st.sidebar.title(f"👤 歡迎回來，{st.session_state['username']}！")
st.sidebar.metric("🏦 雲端可用現金", f"${st.session_state['cash_balance']:,.0f}")
if st.sidebar.button("登出系統"):
    st.session_state["logged_in"] = False
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.title("⚙️ 策略參數控制台")
st.sidebar.markdown("### 💡 分析師推薦實戰組合")
st.sidebar.info("""
**🟢 穩健波段流 (適合 0050, 大型權值股)**
* **買點全開：** 突破(桃紅) + 拉回(綠) + 20MA回踩(藍)
* **賣點只開：** MACD死叉(藍) + 破月線(黑)
""")
st.sidebar.markdown("---")

st.sidebar.subheader("🛡️ 總體趨勢與視覺化控管")
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
    except:
        return ticker

@st.cache_data(ttl=3600)
def load_data(ticker, days=1825): 
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=days)
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
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
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + rs))
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
    
    df['Bias_20MA'] = (df['Close'] - df['SMA_20']) / df['SMA_20'] * 100
    
    conditions = [
        (df['RSI'] >= 70) | (df['Bias_20MA'] >= bias_limit),
        (df['RSI'] >= 60) | (df['Bias_20MA'] >= (bias_limit * 0.7)),
        (df['Close'] < df['SMA_60'])
    ]
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
# 🗂️ 建立分頁
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["📊 個股詳細分析", "🚀 策略選股掃描器", "💰 策略回測實驗室", "⚖️ 雲端金庫與再平衡"])

# ------------------------------------------
# 分頁一：個股詳細分析 (包含彈性建倉系統)
# ------------------------------------------
with tab1:
    ticker_input_raw = st.text_input("🔍 請輸入要分析的股票代碼", value="2330.TW", key="tab1_input")
    ticker_input = ticker_input_raw.strip().upper()
    df_raw = load_data(ticker_input, days=1825) 
    
    if not df_raw.empty:
        stock_name = get_stock_name(ticker_input)
        st.markdown(f"## 📊 {stock_name} ({ticker_input})")
        df = calculate_indicators_and_signals(df_raw.copy(), bbw_factor, vol_factor, kd_threshold, use_adx_filter, cooldown_days, safe_bias_limit)
        
        if show_trade_lines:
            df['Combined_Buy'] = False
            if use_breakout: df['Combined_Buy'] = df['Combined_Buy'] | df['Buy_Breakout']
            if use_pullback: df['Combined_Buy'] = df['Combined_Buy'] | df['Buy_Pullback']
            if use_ma_bounce: df['Combined_Buy'] = df['Combined_Buy'] | df['Buy_MABounce']
            if use_5ma_bounce: df['Combined_Buy'] = df['Combined_Buy'] | df['Buy_5MABounce']
            
            df['Combined_Sell'] = False
            if use_sell_5ma: df['Combined_Sell'] = df['Combined_Sell'] | df['Sell_5MA']
            if use_sell_kd: df['Combined_Sell'] = df['Combined_Sell'] | df['Sell_KD']
            if use_sell_rsi: df['Combined_Sell'] = df['Combined_Sell'] | df['Sell_RSI']
            if use_sell_macd: df['Combined_Sell'] = df['Combined_Sell'] | df['Sell_MACD']
            if use_sell_ma: df['Combined_Sell'] = df['Combined_Sell'] | df['Sell_MA20']

            trades_viz = []
            pos = 0
            entry_p = 0
            entry_d = None
            for i in range(len(df)):
                if pos == 0 and df['Combined_Buy'].iloc[i]:
                    pos = 1
                    entry_p = df['Close'].iloc[i]
                    entry_d = df.index[i]
                elif pos == 1 and df['Combined_Sell'].iloc[i]:
                    pos = 0
                    exit_p = df['Close'].iloc[i]
                    exit_d = df.index[i]
                    ret = (exit_p - entry_p) / entry_p * 100
                    diff = exit_p - entry_p 
                    trades_viz.append({
                        'buy_date': entry_d, 'buy_price': entry_p, 'sell_date': exit_d, 'sell_price': exit_p, 'return': ret, 'diff': diff, 'sell_high': df['High'].iloc[i], 'atr': df['ATR_14'].iloc[i]
                    })

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # ==========================================
        # ★ 模塊一：系統建議區 (僅提供參考，不綁定下單)
        # ==========================================
        st.markdown("### 🧮 系統建倉建議 (風險平價計算機)")
        col_calc1, col_calc2 = st.columns(2)
        with col_calc1:
            st.metric("🏦 目前雲端可用資金", f"${st.session_state['cash_balance']:,.0f}")
        with col_calc2:
            risk_pct = st.slider("⚠️ 單筆願意承受的最大總資金虧損 (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)

        total_capital = st.session_state['cash_balance']
        risk_amount = total_capital * (risk_pct / 100.0)
        entry_price = latest['Close']
        stop_loss_price = latest['SMA_20']
        recommended_shares = 0

        if entry_price > stop_loss_price and total_capital > 0:
            risk_per_share = entry_price - stop_loss_price
            shares_by_risk = int(risk_amount // risk_per_share)
            shares_by_cash = int(total_capital // entry_price)
            recommended_shares = min(shares_by_risk, shares_by_cash)
            invest_amount = recommended_shares * entry_price
            
            st.success(f"📈 **系統建議買進股數： {recommended_shares:,.0f} 股**")
            st.info(f"💡 預計動用資金：${invest_amount:,.0f} ｜ 若看錯停損，最多賠付風險金額：${recommended_shares * risk_per_share:,.0f}")
        else:
            st.error("🚨 目前股價低於防守線 20MA，處於空頭弱勢區。系統強烈建議：【空手觀望，0 股】！")
            
        st.markdown("---")

        # ==========================================
        # ★ 模塊二：使用者手動建倉區 (賦予最高決策權)
        # ==========================================
        st.markdown("### ✍️ 建立專屬倉位 (交易紀錄)")
        st.caption("請依照您實際在券商軟體成交的數字填寫。系統不會強制阻擋您的交易決策。")
        
        with st.form("manual_trade_form"):
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                manual_ticker = st.text_input("股票代碼", value=ticker_input)
            with col_m2:
                default_shares = max(1, int(recommended_shares)) if recommended_shares > 0 else 1000
                manual_shares = st.number_input("實際買進股數", min_value=1, value=default_shares)
            with col_m3:
                manual_price = st.number_input("實際成交單價", min_value=0.01, value=float(latest['Close']), format="%.2f")
            
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
                    st.success(f"✅ 成功買進 {manual_ticker.upper()} 共 {manual_shares} 股！請前往【雲端金庫】查看。")
                    st.rerun()

        st.markdown("---")
        
        st.markdown(f"### 🛡️ 今日戰情室：進場風險評估 (日期: {latest.name.strftime('%Y-%m-%d')})")
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("最新收盤價", f"{latest['Close']:.2f}", f"{(latest['Close'] - prev['Close']):.2f} ({((latest['Close'] - prev['Close']) / prev['Close']) * 100:.2f}%)")
        with col2: st.metric("與 20MA 乖離率", f"{latest['Bias_20MA']:.2f}%")
        with col3: st.metric("RSI (14)", f"{latest['RSI']:.1f}")
        
        status_color = "🟢" if "安全" in latest['Status_Signal'] else "🟡" if "留意" in latest['Status_Signal'] else "🔴" if "危險" in latest['Status_Signal'] else "⚫"
        with col4: st.markdown(f"**判定**<br><span style='font-size:20px'>{latest['Status_Signal']}</span>", unsafe_allow_html=True)
        st.markdown("---")
        
        # 畫圖區塊 (強制關閉範圍滑桿)
        fig = make_subplots(rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.04, 
                            row_heights=[0.4, 0.12, 0.12, 0.12, 0.12, 0.12],
                            subplot_titles=("K線與均線 (含持倉獲利方塊)", "成交量 (Volume)", "KD 指標 (9)", "MACD 指標", "RSI 指標 (14)", "OBV 能量潮"))
        fig.update_annotations(x=0, xanchor="left", font_size=14, font_color="gray")
        
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green', customdata=df['Hover_Text'], hovertemplate="<b>日期:</b> %{x|%Y-%m-%d}<br><b>收:</b> %{close:.2f}<br><br>%{customdata}<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='magenta', width=1.5), name='5MA(週)'), row=1, col=1) 
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1.5), name='20MA(月)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], line=dict(color='green', width=2), name='60MA(季)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)

        if use_breakout: fig.add_trace(go.Scatter(x=df[df['Buy_Breakout']].index, y=df.loc[df['Buy_Breakout'], 'Low'] - df.loc[df['Buy_Breakout'], 'ATR_14'] * 0.4, mode='markers', marker=dict(symbol='triangle-up', size=14, color='magenta', line=dict(width=1, color='DarkSlateGrey')), name='買：突破'), row=1, col=1)
        if use_pullback: fig.add_trace(go.Scatter(x=df[df['Buy_Pullback']].index, y=df.loc[df['Buy_Pullback'], 'Low'] - df.loc[df['Buy_Pullback'], 'ATR_14'] * 0.8, mode='markers', marker=dict(symbol='triangle-up', size=13, color='lime', line=dict(width=1, color='DarkSlateGrey')), name='買：KD拉回'), row=1, col=1)
        if use_ma_bounce: fig.add_trace(go.Scatter(x=df[df['Buy_MABounce']].index, y=df.loc[df['Buy_MABounce'], 'Low'] - df.loc[df['Buy_MABounce'], 'ATR_14'] * 1.2, mode='markers', marker=dict(symbol='triangle-up', size=13, color='dodgerblue', line=dict(width=1, color='DarkSlateGrey')), name='買：20MA回踩'), row=1, col=1)
        if use_5ma_bounce: fig.add_trace(go.Scatter(x=df[df['Buy_5MABounce']].index, y=df.loc[df['Buy_5MABounce'], 'Low'] - df.loc[df['Buy_5MABounce'], 'ATR_14'] * 1.6, mode='markers', marker=dict(symbol='triangle-up', size=12, color='gold', line=dict(width=1, color='DarkSlateGrey')), name='買：5MA回踩'), row=1, col=1)

        if use_sell_5ma: fig.add_trace(go.Scatter(x=df[df['Sell_5MA']].index, y=df.loc[df['Sell_5MA'], 'High'] + df.loc[df['Sell_5MA'], 'ATR_14'] * 0.4, mode='markers', marker=dict(symbol='triangle-down', size=12, color='red', line=dict(width=1, color='DarkSlateGrey')), name='賣：破5MA'), row=1, col=1)
        if use_sell_kd: fig.add_trace(go.Scatter(x=df[df['Sell_KD']].index, y=df.loc[df['Sell_KD'], 'High'] + df.loc[df['Sell_KD'], 'ATR_14'] * 0.8, mode='markers', marker=dict(symbol='triangle-down', size=12, color='orange', line=dict(width=1, color='DarkSlateGrey')), name='賣：KD死叉'), row=1, col=1)
        if use_sell_rsi: fig.add_trace(go.Scatter(x=df[df['Sell_RSI']].index, y=df.loc[df['Sell_RSI'], 'High'] + df.loc[df['Sell_RSI'], 'ATR_14'] * 1.2, mode='markers', marker=dict(symbol='triangle-down', size=12, color='purple', line=dict(width=1, color='DarkSlateGrey')), name='賣：RSI過熱'), row=1, col=1)
        if use_sell_macd: fig.add_trace(go.Scatter(x=df[df['Sell_MACD']].index, y=df.loc[df['Sell_MACD'], 'High'] + df.loc[df['Sell_MACD'], 'ATR_14'] * 1.6, mode='markers', marker=dict(symbol='triangle-down', size=12, color='blue', line=dict(width=1, color='DarkSlateGrey')), name='賣：MACD死叉'), row=1, col=1)
        if use_sell_ma: fig.add_trace(go.Scatter(x=df[df['Sell_MA20']].index, y=df.loc[df['Sell_MA20'], 'High'] + df.loc[df['Sell_MA20'], 'ATR_14'] * 2.0, mode='markers', marker=dict(symbol='triangle-down', size=13, color='black', line=dict(width=1, color='DarkSlateGrey')), name='賣：破月線'), row=1, col=1)

        if show_trade_lines:
            for t in trades_viz:
                is_profit = t['return'] > 0
                line_color = "rgba(0, 200, 0, 0.8)" if is_profit else "rgba(255, 0, 0, 0.8)"
                fill_color = "rgba(0, 200, 0, 0.15)" if is_profit else "rgba(255, 0, 0, 0.15)"
                bg_color = "green" if is_profit else "red"
                sign = "+" if is_profit else ""
                text = f"{sign}{t['diff']:.2f} ({sign}{t['return']:.1f}%)"
                
                fig.add_shape(type="rect", x0=t['buy_date'], y0=t['buy_price'], x1=t['sell_date'], y1=t['sell_price'], fillcolor=fill_color, line=dict(color=line_color, width=2), row=1, col=1)
                fig.add_annotation(x=t['sell_date'], y=t['sell_high'] + t['atr'] * 2.8, text=f"<b>{text}</b>", showarrow=True, arrowhead=1, arrowsize=1, arrowwidth=1, arrowcolor=line_color, ax=0, ay=-30, font=dict(color="white", size=11), bgcolor=bg_color, bordercolor="white", borderwidth=1, borderpad=3, row=1, col=1)

        vol_colors = ['red' if c >= o else 'green' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=vol_colors), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Vol_5MA'], line=dict(color='orange', width=1.5, dash='dot'), name='5日均量'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], line=dict(color='blue'), name='K'), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], line=dict(color='orange'), name='D'), row=3, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="gray", row=3, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="gray", row=3, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df['Histogram'], name='MACD', marker_color=['red' if v > 0 else 'green' for v in df['Histogram']]), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='orange', width=1.5), name='MACD 線'), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Signal'], line=dict(color='purple', width=1.5), name='訊號線'), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='darkred'), name='RSI'), row=5, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="gray", row=5, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="gray", row=5, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], line=dict(color='teal'), name='OBV'), row=6, col=1)

        fig.update_layout(height=1300, hovermode="x unified", dragmode='pan', showlegend=False, xaxis_rangeslider_visible=False)
        default_start = df.index[-1] - pd.Timedelta(days=150)
        dt_breaks = [d.strftime("%Y-%m-%d") for d in pd.date_range(start=df.index[0], end=df.index[-1]) if d not in df.index]
        fig.update_xaxes(range=[default_start, df.index[-1] + pd.Timedelta(days=10)], rangebreaks=[dict(values=dt_breaks)], showspikes=True, spikemode='across', spikethickness=1, spikecolor='grey', spikedash='dot')
        fig.update_yaxes(showspikes=True, spikemode='across', spikethickness=1, spikecolor='grey', spikedash='dot', nticks=15)
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'modeBarButtonsToAdd': ['drawline', 'drawrect', 'eraseshape']})

# ------------------------------------------
# 分頁二 & 三：維持原樣
# ------------------------------------------
with tab2: st.info("掃描器運作中... 請切換分頁查看")
with tab3: st.info("回測實驗室運作中... 請切換分頁查看")

# ------------------------------------------
# 分頁四：⚖️ 雲端金庫與大盤再平衡 (加強版容錯)
# ------------------------------------------
with tab4:
    st.header("⚖️ 雲端專屬金庫 ＆ 大盤氣象再平衡")
    st.markdown("系統自動讀取你的庫存，並根據台股大盤判斷你目前的資金水位是否安全。")
    
    if st.button("🔄 刷新雲端帳本與大盤數據", type="primary"):
        ws_holdings = sh.worksheet("Holdings")
        records = ws_holdings.get_all_records()
        all_holdings = pd.DataFrame(records)
        
        # 防錯機制：檢查資料表是不是空的
        if not all_holdings.empty and 'Username' in all_holdings.columns:
            user_holdings = all_holdings[all_holdings['Username'] == st.session_state["username"]]
        else:
            user_holdings = pd.DataFrame() 
        
        twii = load_data("^TWII", days=100)
        twii['SMA_60'] = twii['Close'].rolling(window=60).mean()
        twii_last = twii.iloc[-1]
        
        score = 0
        if twii_last['Close'] > twii_last['SMA_60']: score += 50 
        suggested_exposure_pct = 80 if score >= 50 else 30
        
        st.markdown("### 🌦️ 大盤氣象台")
        weather = "🌞 晴朗 (多頭趨勢)" if score >= 50 else "⛈️ 暴雨 (空頭趨勢)"
        st.info(f"**台股加權指數 (^TWII) 目前狀態：** {weather}。目前指數：{twii_last['Close']:.0f}，季線：{twii_last['SMA_60']:.0f}")
        
        total_market_value = 0
        st.markdown("### 💼 我的雲端庫存清單")
        if not user_holdings.empty:
            # 防禦升級 1：先預設所有欄位
            user_holdings = user_holdings.copy()
            user_holdings['目前股價'] = user_holdings['Entry_Price']
            user_holdings['目前市值'] = user_holdings['Total_Cost']
            user_holdings['未實現損益 (%)'] = 0.0

            for idx, row in user_holdings.iterrows():
                try:
                    # 防禦升級 2：改用 history API 更穩定
                    hist = yf.Ticker(row['Ticker']).history(period="5d")
                    if not hist.empty:
                        curr_price = float(hist['Close'].iloc[-1])
                        mkt_val = curr_price * row['Shares']
                        
                        user_holdings.at[idx, '目前股價'] = round(curr_price, 2)
                        user_holdings.at[idx, '目前市值'] = round(mkt_val, 0)
                        user_holdings.at[idx, '未實現損益 (%)'] = round(((curr_price - row['Entry_Price']) / row['Entry_Price']) * 100, 2)
                        
                        total_market_value += mkt_val
                    else:
                        total_market_value += row['Total_Cost']
                except Exception:
                    total_market_value += row['Total_Cost']
                    
            st.dataframe(user_holdings[['Ticker', 'Shares', 'Entry_Price', '目前股價', 'Total_Cost', '目前市值', '未實現損益 (%)']], use_container_width=True)
        else:
            st.warning("目前雲端金庫空空如也，趕快去個股分析頁面建倉吧！")
            
        total_equity = st.session_state["cash_balance"] + total_market_value
        current_exposure_pct = (total_market_value / total_equity) * 100 if total_equity > 0 else 0
        
        st.markdown("### ⚖️ 資金水位再平衡建議")
        col_r1, col_r2, col_r3 = st.columns(3)
        col_r1.metric("總資產淨值 (現金+股票)", f"${total_equity:,.0f}")
        col_r2.metric("目前持股水位", f"{current_exposure_pct:.1f}%")
        col_r3.metric("大盤建議持股水位", f"{suggested_exposure_pct}%")
        
        diff_pct = current_exposure_pct - suggested_exposure_pct
        if diff_pct > 5:
            st.error(f"🚨 **危險！你的持股水位過高！** 建議減碼 {diff_pct:.1f}% (約賣出 ${total_equity * (diff_pct/100):,.0f} 的股票變回現金)。")
        elif diff_pct < -5:
            st.success(f"🟢 **水位安全，可逢低佈局！** 距離建議上限還有 {-diff_pct:.1f}% (約 ${total_equity * (-diff_pct/100):,.0f}) 的空間可進場。")
        else:
            st.info("👌 **目前資金水位完美平衡，請保持現狀！**")
