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
# ☁️ 雲端資料庫連線設定 (Google Sheets)
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
# ⚙️ 左側邊欄設定 (新增雙引擎切換)
# ==========================================
st.sidebar.title(f"👤 歡迎回來，{st.session_state['username']}！")
st.sidebar.metric("🏦 雲端可用現金", f"${st.session_state['cash_balance']:,.0f}")
if st.sidebar.button("登出系統"):
    st.session_state["logged_in"] = False
    st.rerun()

st.sidebar.markdown("---")
# ★ 新增：雙引擎交易流派切換
st.sidebar.title("🧠 核心交易流派選擇")
trade_style = st.sidebar.radio("請選擇您的操作信仰：", [
    "📈 順勢動能 (右側交易：確認向上才買)",
    "🛒 價值抄底 (左側交易：別人恐懼我貪婪)"
])

st.sidebar.markdown("---")
sidebar_trade_container = st.sidebar.container()
st.sidebar.markdown("---")

st.sidebar.title("⚙️ 策略參數控制台")
show_trade_lines = st.sidebar.checkbox("開啟【買賣區間透視方塊】", value=True)
use_adx_filter = st.sidebar.checkbox("開啟【ADX 趨勢過濾】", value=True)
cooldown_days = st.sidebar.slider("訊號冷卻天數", min_value=1, max_value=10, value=5)
safe_bias_limit = st.sidebar.slider("進場安全乖離率上限 (%)", min_value=1.0, max_value=15.0, value=5.0)

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
    df['Status_Signal'] = np.select(conditions, ["🔴 極度危險 (勿追高)", "🟡 留意拉回風險", "⚫ 空頭趨勢 (不建議)"], default="🟢 安全區間 (可佈局)")
    df['Hover_Text'] = ("20MA乖離率: " + df['Bias_20MA'].round(2).astype(str) + "%<br>RSI (14): " + df['RSI'].round(1).astype(str) + "<br>進場判定: <b>" + df['Status_Signal'] + "</b>")
    
    df['Prev_Close'] = df['Close'].shift(1)
    df['TR'] = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Prev_Close']), abs(df['Low'] - df['Prev_Close'])))
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']), np.maximum(df['High'] - df['High'].shift(1), 0), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)), np.maximum(df['Low'].shift(1) - df['Low'], 0), 0)
    df['ATR_14'] = df['TR'].ewm(alpha=1/14, adjust=False).mean()
    
    df['Vol_5MA'] = df['Volume'].rolling(window=5).mean()
    return df

def draw_gauge(val, max_val, title, color):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=val, 
        number={'suffix': "%", 'font': {'size': 18, 'color': color}},
        title={'text': title, 'font': {'size': 12}},
        gauge={'axis': {'range': [0, max_val], 'tickwidth': 1, 'tickcolor': "darkblue"},
               'bar': {'color': color}, 'bgcolor': "white", 'borderwidth': 2, 'bordercolor': "gray"}
    ))
    fig.update_layout(height=120, margin=dict(l=10, r=10, t=60, b=10))
    return fig

# ==========================================
# 🗂️ 建立分頁
# ==========================================
tab1, tab2, tab3, tab4 = st.tabs(["📊 個股詳細分析", "🚀 策略選股掃描器", "💰 策略回測實驗室", "⚖️ 雲端金庫與再平衡"])

# ------------------------------------------
# 分頁一：個股詳細分析 (雙引擎計算機)
# ------------------------------------------
with tab1:
    ticker_input_raw = st.text_input("🔍 請輸入要分析的股票代碼", value="2330.TW", key="tab1_input")
    ticker_input = ticker_input_raw.strip().upper()
    df_raw = load_data(ticker_input, days=1825) 
    
    if not df_raw.empty:
        stock_name = get_stock_name(ticker_input)
        st.markdown(f"## 📊 {stock_name} ({ticker_input})")
        df = calculate_indicators_and_signals(df_raw.copy(), 1.1, 1.5, 50, True, 5, 5.0)
        latest, prev = df.iloc[-1], df.iloc[-2]
        
        # ==========================================
        # ★ 雙引擎建倉計算機
        # ==========================================
        st.markdown(f"### 🧮 系統建倉建議 ({'📈 順勢動能' if '順勢' in trade_style else '🛒 價值抄底'}模型)")
        col_calc1, col_calc2 = st.columns(2)
        with col_calc1: st.metric("🏦 目前雲端可用資金", f"${st.session_state['cash_balance']:,.0f}")
        with col_calc2: risk_pct = st.slider("⚠️ 單筆願意承受最大虧損 (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)

        total_capital = st.session_state['cash_balance']
        risk_amount = total_capital * (risk_pct / 100.0)
        entry_price = latest['Close']
        recommended_shares = 0

        if "順勢" in trade_style:
            # 【右側順勢邏輯】嚴格防守 20MA
            stop_loss_price = latest['SMA_20']
            if entry_price > stop_loss_price and total_capital > 0:
                risk_per_share = entry_price - stop_loss_price
                recommended_shares = min(int(risk_amount // risk_per_share), int(total_capital // entry_price))
                st.success(f"📈 **順勢建議買進股數： {recommended_shares:,.0f} 股** (動用資金：${recommended_shares * entry_price:,.0f})")
            else: 
                st.error("🚨 目前股價低於防守線 20MA，處於空頭弱勢區。順勢策略建議：【空手觀望，0 股】！")
        else:
            # 【左側抄底邏輯】金字塔分批建倉法
            assumed_risk_per_share = entry_price * 0.10 # 預設若再跌 10% 為極限風險
            max_shares = min(int(risk_amount // assumed_risk_per_share), int(total_capital // entry_price))
            
            if entry_price > latest['SMA_20']:
                st.warning("⚖️ 目前股價在月線之上，無特價空間。價值投資建議：【耐心等待回檔，0 股】")
            else:
                if latest['RSI'] < 30 or entry_price < latest['Lower_Band']:
                    tier = "🔴 極度恐慌區 (價值浮現，重倉抄底)"
                    weight = 1.0
                elif latest['RSI'] < 40 or entry_price < latest['SMA_60']:
                    tier = "🟡 跌深反彈區 (分批加碼建倉)"
                    weight = 0.5
                else:
                    tier = "🟢 初步回檔區 (試單水溫)"
                    weight = 0.2
                
                recommended_shares = int(max_shares * weight)
                st.success(f"🛒 **{tier}** -> 建議買進： **{recommended_shares:,.0f} 股**")
                st.info(f"💡 金字塔建倉權重：{weight*100}% | 預計動用資金：${recommended_shares * entry_price:,.0f}")
            
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
                        ws_holdings = sh.worksheet("Holdings")
                        ws_users = sh.worksheet("Users")
                        ws_holdings.append_row([st.session_state["username"], manual_ticker.upper(), manual_shares, manual_price, actual_cost, datetime.datetime.now().strftime("%Y-%m-%d")])
                        
                        new_cash = st.session_state['cash_balance'] - actual_cost
                        df_users = pd.DataFrame(ws_users.get_all_records())
                        row_idx = df_users.index[df_users['Username'] == st.session_state["username"]].tolist()[0] + 2 
                        ws_users.update_cell(row_idx, 4, new_cash)
                        st.session_state["cash_balance"] = new_cash
                        st.success(f"✅ 已買進 {manual_ticker.upper()}！")
                        st.rerun()

        st.markdown(f"### 🛡️ 今日戰情室：進場風險評估 (日期: {latest.name.strftime('%Y-%m-%d')})")
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("最新收盤價", f"{latest['Close']:.2f}", f"{(latest['Close'] - prev['Close']):.2f} ({((latest['Close'] - prev['Close']) / prev['Close']) * 100:.2f}%)")
        with col2: st.metric("與 20MA 乖離率", f"{latest['Bias_20MA']:.2f}%")
        with col3: st.metric("RSI (14)", f"{latest['RSI']:.1f}")
        with col4: st.markdown(f"**判定**<br><span style='font-size:20px'>{latest['Status_Signal']}</span>", unsafe_allow_html=True)
        st.markdown("---")
        
        # 繪圖區塊
        fig = make_subplots(rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.04, 
                            row_heights=[0.4, 0.12, 0.12, 0.12, 0.12, 0.12],
                            subplot_titles=("K線與均線", "成交量 (Volume)", "KD 指標 (9)", "MACD 指標", "RSI 指標 (14)", "OBV 能量潮"))
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green', customdata=df['Hover_Text'], hovertemplate="<b>日期:</b> %{x|%Y-%m-%d}<br><b>收:</b> %{close:.2f}<br><br>%{customdata}<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='magenta', width=1.5), name='5MA(週)'), row=1, col=1) 
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1.5), name='20MA(月)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], line=dict(color='green', width=2), name='60MA(季)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash')), row=1, col=1)
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
        dt_breaks = [d.strftime("%Y-%m-%d") for d in pd.date_range(start=df.index[0], end=df.index[-1]) if d not in df.index]
        fig.update_xaxes(range=[df.index[-1] - pd.Timedelta(days=150), df.index[-1] + pd.Timedelta(days=10)], rangebreaks=[dict(values=dt_breaks)])
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

with tab2: st.info("🚀 掃描器運作中...")
with tab3: st.info("💰 回測實驗室運作中...")

# ------------------------------------------
# 分頁四：⚖️ 雲端金庫與大盤儀表板 (雙引擎動態)
# ------------------------------------------
with tab4:
    st.header("⚖️ 雲端專屬金庫 ＆ 戰情儀表板")
    
    if st.button("🔄 刷新雲端帳本與大盤數據", type="primary"):
        with st.spinner('正在分析大盤四大線性指標與雲端金庫...'):
            twii = load_data("^TWII", days=100)
            vix = load_data("^VIX", days=30)
            
            if not twii.empty:
                twii['SMA_20'] = twii['Close'].rolling(window=20).mean()
                twii['SMA_60'] = twii['Close'].rolling(window=60).mean()
                tw_last = twii.iloc[-1]
                vix_last = vix['Close'].iloc[-1] if not vix.empty else 20
                
                bias_60 = ((tw_last['Close'] - tw_last['SMA_60']) / tw_last['SMA_60']) * 100
                bias_20 = ((tw_last['Close'] - tw_last['SMA_20']) / tw_last['SMA_20']) * 100

                # ==========================================
                # ★ 雙引擎大盤計分邏輯
                # ==========================================
                if "順勢" in trade_style:
                    # 順勢派：跌破扣分，VIX高扣分
                    s_trend = float(np.clip(40 * (bias_60 + 5) / 10, 0, 40))
                    s_mom = float(np.clip(20 * (bias_20 + 3) / 6, 0, 20))
                    s_bias = float(np.clip(20 - (20 * (bias_20 + 5) / 10), 0, 20))
                    s_vix = float(np.clip(20 - (20 * (vix_last - 15) / 20), 0, 20))
                    t_trend, t_mom, t_bias, t_vix = "季線趨勢 (滿分40%)", "月線動能 (滿分20%)", "乖離過熱度 (滿分20%)", "VIX 安全度 (滿分20%)"
                else:
                    # 價值抄底派：跌破越深越高分，VIX越高越高分
                    s_trend = float(np.clip(40 * (-bias_60 + 5) / 10, 0, 40))
                    s_mom = float(np.clip(20 * (-bias_20 + 3) / 6, 0, 20))
                    s_bias = float(np.clip(20 * (-bias_20 + 5) / 10, 0, 20))
                    s_vix = float(np.clip(20 * (vix_last - 15) / 20, 0, 20))
                    t_trend, t_mom, t_bias, t_vix = "季線跌深度 (滿分40%)", "月線超賣度 (滿分20%)", "負乖離價值 (滿分20%)", "VIX 恐慌度 (滿分20%)"

                total_score = round(s_trend + s_mom + s_bias + s_vix, 1)
                
                st.session_state.market_scores = {
                    'trend': round(s_trend, 1), 'mom': round(s_mom, 1), 
                    'bias': round(s_bias, 1), 'vix': round(s_vix, 1), 
                    'total': total_score,
                    'titles': [t_trend, t_mom, t_bias, t_vix]
                }
            
            ws_holdings = sh.worksheet("Holdings")
            all_holdings = pd.DataFrame(ws_holdings.get_all_records())
            
            if not all_holdings.empty and 'Username' in all_holdings.columns:
                uh = all_holdings[all_holdings['Username'] == st.session_state["username"]].copy()
                uh['目前股價'] = uh['Entry_Price']; uh['目前市值'] = uh['Total_Cost']; uh['未實現損益 (%)'] = 0.0
                total_mkt_val = 0
                for idx, row in uh.iterrows():
                    try:
                        hist = yf.Ticker(row['Ticker']).history(period="5d")
                        if not hist.empty:
                            curr_p = float(hist['Close'].iloc[-1])
                            uh.at[idx, '目前股價'] = round(curr_p, 2)
                            uh.at[idx, '目前市值'] = round(curr_p * row['Shares'], 0)
                            uh.at[idx, '未實現損益 (%)'] = round(((curr_p - row['Entry_Price']) / row['Entry_Price']) * 100, 2)
                            total_mkt_val += (curr_p * row['Shares'])
                        else: total_mkt_val += row['Total_Cost']
                    except: total_mkt_val += row['Total_Cost']
                
                st.session_state.user_holdings = uh
                st.session_state.total_mkt_val = total_mkt_val
            else:
                st.session_state.user_holdings = pd.DataFrame()
                st.session_state.total_mkt_val = 0
                
            st.session_state.market_fetched = True

    if st.session_state.market_fetched:
        st.markdown(f"### 🌦️ 大盤氣象台 ({'順勢多頭防守' if '順勢' in trade_style else '逆勢價值抄底'}模型)")
        ms = st.session_state.market_scores
        
        def get_color(val, max_val):
            if val >= max_val * 0.8: return "limegreen"
            elif val <= max_val * 0.4: return "crimson"
            else: return "gold"

        col_g1, col_g2, col_g3, col_g4 = st.columns(4)
        with col_g1: st.plotly_chart(draw_gauge(ms['trend'], 40, ms['titles'][0], get_color(ms['trend'], 40)), use_container_width=True)
        with col_g2: st.plotly_chart(draw_gauge(ms['mom'], 20, ms['titles'][1], get_color(ms['mom'], 20)), use_container_width=True)
        with col_g3: st.plotly_chart(draw_gauge(ms['bias'], 20, ms['titles'][2], get_color(ms['bias'], 20)), use_container_width=True)
        with col_g4: st.plotly_chart(draw_gauge(ms['vix'], 20, ms['titles'][3], get_color(ms['vix'], 20)), use_container_width=True)
        
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
        
        st.markdown("### 💼 我的雲端庫存清單")
        df_h = st.session_state.user_holdings
        
        if not df_h.empty:
            view_mode = st.radio("👀 請選擇檢視模式：", ["📊 彙總視角 (按股票合併計算)", "📝 明細視角 (逐筆交易紀錄)"], horizontal=True)
            csv_data = None
            if "彙總" in view_mode:
                summary = df_h.groupby('Ticker').agg({
                    'Shares': 'sum', 'Total_Cost': 'sum', '目前股價': 'first'
                }).reset_index()
                summary['平均成本價'] = (summary['Total_Cost'] / summary['Shares']).round(2)
                summary['目前總市值'] = (summary['Shares'] * summary['目前股價']).round(0)
                summary['總未實現損益 (%)'] = (((summary['目前股價'] - summary['平均成本價']) / summary['平均成本價']) * 100).round(2)
                summary = summary[['Ticker', 'Shares', '平均成本價', '目前股價', 'Total_Cost', '目前總市值', '總未實現損益 (%)']]
                st.dataframe(summary, use_container_width=True)
                csv_data = summary.to_csv(index=False).encode('utf-8-sig')
            else:
                detail_df = df_h[['Ticker', 'Shares', 'Entry_Price', '目前股價', 'Total_Cost', '目前市值', '未實現損益 (%)', 'Buy_Date']]
                st.dataframe(detail_df, use_container_width=True)
                csv_data = detail_df.to_csv(index=False).encode('utf-8-sig')
            
            st.download_button(label="📥 一鍵匯出 Excel 對帳單 (CSV)", data=csv_data, file_name=f"Quant_Portfolio_{datetime.datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", type="primary")
        else:
            st.warning("目前雲端金庫空空如也，趕快去左側側邊欄建倉吧！")
