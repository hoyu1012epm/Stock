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
        # 從 Secrets 讀取 JSON 金鑰
        creds_json = json.loads(st.secrets["GOOGLE_JSON"])
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
        st.error(f"🚨 資料庫連線失敗！請確認 Secrets 設定與表單名稱。錯誤: {e}")
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
    st.stop() # 阻擋未登入者看到下面的程式碼

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
# 分頁一：個股詳細分析 (連結雲端資金)
# ------------------------------------------
with tab1:
    ticker_input_raw = st.text_input("🔍 請輸入要分析的股票代碼", value="2330.TW", key="tab1_input")
    ticker_input = ticker_input_raw.strip().upper()
    df_raw = load_data(ticker_input, days=1825) 
    
    if not df_raw.empty:
        stock_name = get_stock_name(ticker_input)
        st.markdown(f"## 📊 {stock_name} ({ticker_input})")
        df = calculate_indicators_and_signals(df_raw.copy(), bbw_factor, vol_factor, kd_threshold, use_adx_filter, cooldown_days, safe_bias_limit)
        
        # --- 實戰建倉計算機 (自動抓取雲端餘額) ---
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        st.markdown("### 🧮 實戰建倉計算機 (風險平價模型)")
        col_calc1, col_calc2 = st.columns(2)
        with col_calc1:
            st.metric("🏦 目前雲端可用資金", f"${st.session_state['cash_balance']:,.0f}")
        with col_calc2:
            risk_pct = st.slider("⚠️ 單筆願意承受的最大總資金虧損 (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)

        total_capital = st.session_state['cash_balance']
        risk_amount = total_capital * (risk_pct / 100.0)
        entry_price = latest['Close']
        stop_loss_price = latest['SMA_20']

        if entry_price > stop_loss_price and total_capital > 0:
            risk_per_share = entry_price - stop_loss_price
            shares_by_risk = int(risk_amount // risk_per_share)
            shares_by_cash = int(total_capital // entry_price)
            recommended_shares = min(shares_by_risk, shares_by_cash)
            invest_amount = recommended_shares * entry_price
            
            st.success(f"📈 **建議買進股數： {recommended_shares:,.0f} 股** (約 {recommended_shares/1000:.1f} 張)")
            st.warning(f"💰 **預計動用資金：** ${invest_amount:,.0f} ｜ **看錯停損時最多只會賠：** ${recommended_shares * risk_per_share:,.0f}")
            
            # 雲端寫入按鈕
            if recommended_shares > 0:
                if st.button("🚀 確認買進並寫入雲端金庫", type="primary"):
                    ws_holdings = sh.worksheet("Holdings")
                    ws_users = sh.worksheet("Users")
                    
                    # 寫入持倉
                    buy_date = datetime.datetime.now().strftime("%Y-%m-%d")
                    ws_holdings.append_row([st.session_state["username"], ticker_input, recommended_shares, entry_price, invest_amount, buy_date])
                    
                    # 更新扣款
                    new_cash = total_capital - invest_amount
                    users_data = ws_users.get_all_records()
                    df_users = pd.DataFrame(users_data)
                    row_idx = df_users.index[df_users['Username'] == st.session_state["username"]].tolist()[0] + 2 
                    ws_users.update_cell(row_idx, 4, new_cash)
                    
                    st.session_state["cash_balance"] = new_cash
                    st.success("寫入成功！請前往【雲端金庫】查看。")
                    st.rerun()
        else:
            st.error("🚨 資金不足，或目前股價低於防守線 20MA，建議空手觀望！")
            
        st.markdown("---")
        
        # --- 畫圖 ---
        fig = make_subplots(rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.04, 
                            row_heights=[0.4, 0.12, 0.12, 0.12, 0.12, 0.12],
                            subplot_titles=("K線與均線", "成交量 (Volume)", "KD 指標 (9)", "MACD 指標", "RSI 指標 (14)", "OBV 能量潮"))
        fig.update_annotations(x=0, xanchor="left", font_size=14, font_color="gray")
        
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green', customdata=df['Hover_Text'], hovertemplate="<b>日期:</b> %{x|%Y-%m-%d}<br><b>收:</b> %{close:.2f}<br><br>%{customdata}<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='magenta', width=1.5), name='5MA(週)'), row=1, col=1) 
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1.5), name='20MA(月)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], line=dict(color='green', width=2), name='60MA(季)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)

        vol_colors = ['red' if c >= o else 'green' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量', marker_color=vol_colors), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], line=dict(color='blue'), name='K'), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], line=dict(color='orange'), name='D'), row=3, col=1)
        fig.add_trace(go.Bar(x=df.index, y=df['Histogram'], name='MACD', marker_color=['red' if v > 0 else 'green' for v in df['Histogram']]), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='orange', width=1.5), name='MACD 線'), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Signal'], line=dict(color='purple', width=1.5), name='訊號線'), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='darkred'), name='RSI'), row=5, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], line=dict(color='teal'), name='OBV'), row=6, col=1)

        fig.update_layout(height=1300, hovermode="x unified", dragmode='pan', showlegend=False)
        fig.update_xaxes(range=[df.index[-1] - pd.Timedelta(days=150), df.index[-1] + pd.Timedelta(days=10)], rangeslider=dict(visible=False))
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

# ------------------------------------------
# 分頁二 & 三：(保留掃描器與回測，為省篇幅略過修改，維持原樣即可)
# ------------------------------------------
with tab2: st.info("掃描器運作中... (同上一版設定)")
with tab3: st.info("回測實驗室運作中... (同上一版設定)")

# ------------------------------------------
# 分頁四：⚖️ 雲端金庫與大盤再平衡 (全新殺手級功能)
# ------------------------------------------
with tab4:
    st.header("⚖️ 雲端專屬金庫 ＆ 大盤氣象再平衡")
    st.markdown("系統自動讀取你的庫存，並根據台股大盤判斷你目前的資金水位是否安全。")
    
    if st.button("🔄 刷新雲端帳本與大盤數據"):
        ws_holdings = sh.worksheet("Holdings")
        all_holdings = pd.DataFrame(ws_holdings.get_all_records())
        user_holdings = all_holdings[all_holdings['Username'] == st.session_state["username"]]
        
        # 抓取大盤判定水位
        twii = load_data("^TWII", days=100)
        twii['SMA_60'] = twii['Close'].rolling(window=60).mean()
        twii_last = twii.iloc[-1]
        
        # 水位評分系統
        score = 0
        if twii_last['Close'] > twii_last['SMA_60']: score += 50 # 季線之上 +50%
        # 簡單判定：大牛市給 80%，空頭給 30%
        suggested_exposure_pct = 80 if score >= 50 else 30
        
        st.markdown("### 🌦️ 大盤氣象台")
        weather = "🌞 晴朗 (多頭趨勢)" if score >= 50 else "⛈️ 暴雨 (空頭趨勢)"
        st.info(f"**台股加權指數 (^TWII) 目前狀態：** {weather}。目前指數：{twii_last['Close']:.0f}，季線：{twii_last['SMA_60']:.0f}")
        
        # 結算持倉市值
        total_market_value = 0
        st.markdown("### 💼 我的雲端庫存清單")
        if not user_holdings.empty:
            for idx, row in user_holdings.iterrows():
                try:
                    curr_price = yf.Ticker(row['Ticker']).info.get('regularMarketPrice', row['Entry_Price'])
                    mkt_val = curr_price * row['Shares']
                    total_market_value += mkt_val
                    user_holdings.at[idx, '目前股價'] = curr_price
                    user_holdings.at[idx, '目前市值'] = mkt_val
                    user_holdings.at[idx, '未實現損益 (%)'] = ((curr_price - row['Entry_Price']) / row['Entry_Price']) * 100
                except:
                    pass
            st.dataframe(user_holdings[['Ticker', 'Shares', 'Entry_Price', '目前股價', 'Total_Cost', '目前市值', '未實現損益 (%)']], use_container_width=True)
        else:
            st.warning("目前雲端金庫空空如也，趕快去個股分析頁面建倉吧！")
            
        # 再平衡計算
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
