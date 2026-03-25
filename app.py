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
import time

# 1. 網頁基本設定
st.set_page_config(page_title="專屬量化操盤副駕 | 區間存股版", layout="wide", initial_sidebar_state="expanded")

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
def load_data(ticker, days=1825, start_date=None, end_date=None): 
    if start_date and end_date:
        fetch_start = pd.to_datetime(start_date) - pd.Timedelta(days=120)
        df = yf.download(ticker, start=fetch_start, end=pd.to_datetime(end_date)+pd.Timedelta(days=1), progress=False)
    else:
        df = yf.download(ticker, start=datetime.datetime.now() - datetime.timedelta(days=days), end=datetime.datetime.now(), progress=False)
    
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    if not df.empty: df.index = pd.to_datetime(df.index).tz_localize(None)
    return df

# ★ 回測不再使用Cooldown，改用區間狀態
def calculate_indicators(df):
    if len(df) < 60: return df 
    df['SMA_5'] = df['Close'].rolling(5).mean()
    df['SMA_10'] = df['Close'].rolling(10).mean()
    df['SMA_20'] = df['Close'].rolling(20).mean()
    df['SMA_60'] = df['Close'].rolling(60).mean()
    df['STD_20'] = df['Close'].rolling(20).std()
    df['Upper_Band'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['Lower_Band'] = df['SMA_20'] - (df['STD_20'] * 2)
    
    delta = df['Close'].diff()
    rs = delta.clip(lower=0).ewm(com=13, adjust=False).mean() / (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ★ 核心區間定義 (Green/Red/White)
    cond_warm = (df['RSI'] >= 70) | (df['High'] >= df['Upper_Band'])
    cond_value = (df['RSI'] <= 45) & (df['Close'] <= df['SMA_20'] * 1.05) & (df['Close'] >= df['SMA_60'] * 0.85)
    
    # 用數字紀錄狀態，方便回測運算
    df['Zone_Code'] = np.select([cond_warm, cond_value], [1, -1], default=0) # Red=1, Green=-1, White=0
    df['Zone_Status'] = np.select([cond_warm, cond_value], ["🔴 升溫區間", "🟢 價值區間"], default="⚪ 空蕩等待")
    
    df['Hover_Text'] = (
        "收: " + df['Close'].round(2).astype(str) + "<br>" +
        "RSI: " + df['RSI'].round(1).astype(str) + "<br>" +
        "狀態: <b>" + df['Zone_Status'] + "</b>"
    )
    df['Hover_Y'] = df['High'].rolling(30, center=True, min_periods=1).max()
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
def sync_global_data():
    with st.spinner('📡 正在同步雲端金庫與大盤數據...'):
        twii = load_data("^TWII", days=100)
        vix = load_data("^VIX", days=30)
        
        if not twii.empty:
            twii['SMA_20'] = twii['Close'].rolling(20).mean(); twii['SMA_60'] = twii['Close'].rolling(60).mean()
            tw_last = twii.iloc[-1]; vix_last = vix['Close'].iloc[-1] if not vix.empty else 20
            bias_60 = ((tw_last['Close'] - tw_last['SMA_60']) / tw_last['SMA_60']) * 100
            bias_20 = ((tw_last['Close'] - tw_last['SMA_20']) / tw_last['SMA_20']) * 100

            s_trend = float(np.clip(40 * (bias_60 + 5) / 10, 0, 40)); s_mom = float(np.clip(20 * (bias_20 + 3) / 6, 0, 20))
            s_bias = float(np.clip(20 - (20 * (bias_20 + 5) / 10), 0, 20)); s_vix = float(np.clip(20 - (20 * (vix_last - 15) / 20), 0, 20))
            titles = ["大盤長線趨勢 (40%)", "大盤短線動能 (20%)", "市場乖離冷卻度 (20%)", "VIX 安定度 (20%)"]

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
# ⚙️ 左側邊欄設定 (★ 大幅簡化，因回測不再使用技術指標符號)
# ==========================================
st.sidebar.title(f"👤 歡迎回來，{st.session_state['username']}！")
st.sidebar.metric("🏦 雲端可用現金", f"${st.session_state['cash_balance']:,.0f}")
if st.sidebar.button("登出系統"): st.session_state["logged_in"] = False; st.rerun()

st.sidebar.markdown("---")
st.sidebar.title("🧠 核心交易流派")
st.sidebar.success("✅ 目前已切換為：【大波段區間存股模型】")

if st.sidebar.button("🔄 同步雲端大盤與帳本", type="primary", use_container_width=True):
    sync_global_data()

if not st.session_state.market_fetched: sync_global_data()

st.sidebar.markdown("---")
sidebar_trade_container = st.sidebar.container()
st.sidebar.markdown("---")

# 控制台只保留圖表顯示控制
st.sidebar.title("⚙️ 圖表控制台")
show_zone_bg = st.sidebar.checkbox("開啟【三大氣候區間背景色】", value=True)

# ★ 下單匣不需要推薦股數，因改為區間自動抄底
with sidebar_trade_container:
    st.markdown("### ✍️ 專屬下單匣")
    with st.form("manual_trade_form"):
        manual_ticker = st.text_input("股票代碼", value="")
        manual_shares = st.number_input("買進股數", min_value=1, value=100)
        manual_price = st.number_input("成交單價", min_value=0.01, format="%.2f")
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

# ==========================================
# 🗂️ 建立分頁
# ==========================================
tab1, tab2, tab3 = st.tabs(["📊 區間分析與下單", "💰 區間回測實驗室", "⚖️ 金庫儀表板"])

# ------------------------------------------
# 分頁一：個股詳細分析 
# ------------------------------------------
with tab1:
    col_s1, col_s2 = st.columns([1, 3])
    with col_s1: market_type = st.selectbox("🌍 市場別", ["上市 (.TW)", "上櫃 (.TWO)", "美股/自訂 (無)"], key="t1_mkt")
    with col_s2: stock_num = st.text_input("🔍 請輸入股票代號 (例：2330)", value="AAPL", key="t1_tkr") 
    
    if "上市" in market_type: suffix = ".TW"
    elif "上櫃" in market_type: suffix = ".TWO"
    else: suffix = ""
    
    ticker_input = f"{stock_num.strip()}{suffix}".upper()
    df_raw = load_data(ticker_input, days=1825) if stock_num else pd.DataFrame()
    
    if not df_raw.empty:
        stock_name = get_stock_name(ticker_input)
        st.markdown(f"## 📊 {stock_name} ({ticker_input})")
        df = calculate_indicators(df_raw.copy())
        latest = df.iloc[-1]
        
        # 戰情室簡化
        st.markdown(f"### 🛡️ 今日戰情 (日期: {latest.name.strftime('%Y-%m-%d')})")
        col1, col2, col3 = st.columns(3)
        col1.metric("最新收盤價", f"{latest['Close']:.2f}")
        col2.metric("RSI (14)", f"{latest['RSI']:.1f}")
        col3.markdown(f"**區間判定**<br><span style='font-size:24px; font-weight:bold;'>{latest['Zone_Status']}</span>", unsafe_allow_html=True)
        st.markdown("---")
        
        # 繪圖區塊 (★ 取消所有小三角形，只留K線與背景色)
        fig = go.Figure()
        
        if show_zone_bg:
            current_zone = 0; start_date = None
            for idx, row in df.iterrows():
                val = row['Zone_Code']
                if val != current_zone:
                    if current_zone != 0 and start_date is not None:
                        color = "rgba(255, 0, 0, 0.1)" if current_zone == 1 else "rgba(0, 255, 0, 0.1)"
                        fig.add_shape(type="rect", x0=start_date, x1=idx, y0=0, y1=1, xref="x", yref="paper", fillcolor=color, line_width=0, layer="below")
                    current_zone = val; start_date = idx if val != 0 else None
            if current_zone != 0 and start_date is not None:
                color = "rgba(255, 0, 0, 0.1)" if current_zone == 1 else "rgba(0, 255, 0, 0.1)"
                fig.add_shape(type="rect", x0=start_date, x1=df.index[-1], y0=0, y1=1, xref="x", yref="paper", fillcolor=color, line_width=0, layer="below")

        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green', showlegend=False, hoverinfo='skip'))
        # 隱形Hover層
        fig.add_trace(go.Scatter(x=df.index, y=df['Hover_Y'], mode='markers', marker=dict(color='rgba(0,0,0,0)', size=1), showlegend=False, customdata=df['Hover_Text'], hovertemplate="<b>日期: %{x|%Y-%m-%d}</b><br>%{customdata}<extra></extra>"))
        
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1.5), name="MA 20", hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], line=dict(color='green', width=2), name="MA 60", hoverinfo='skip'))
        
        dt_breaks = [d.strftime("%Y-%m-%d") for d in pd.date_range(start=df.index[0], end=df.index[-1]) if d not in df.index]
        fig.update_xaxes(showspikes=True, spikemode='across', spikedash='dot', spikecolor='gray', range=[df.index[-1] - pd.Timedelta(days=150), df.index[-1] + pd.Timedelta(days=10)], rangebreaks=[dict(values=dt_breaks)])
        fig.update_layout(height=700, hovermode="x", dragmode='pan', xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})
    else:
        st.warning("⚠️ 請確認股票代碼。")

# ------------------------------------------
# 分頁二：💰 區間回測實驗室 (★ 核心邏輯重寫版)
# ------------------------------------------
with tab3:
    st.header("💰 區間存股回測實驗室 (綠底買、紅底賣)")
    st.markdown("本回測完全依據畫面的 **【🟢 價值區間】買進** 與 **【🔴 升溫區間】賣出**。徹底捨棄短線技術指標訊號。")
    
    col_b1, col_b2 = st.columns([1, 3])
    with col_b1: backtest_market = st.selectbox("🌍 市場別", ["上市 (.TW)", "上櫃 (.TWO)", "美股/自訂 (無)"], key="bt_mkt")
    with col_b2: backtest_ticker_input = st.text_input("🔍 請輸入股票代號", value="2330", key="bt_tkr")
    
    bt_ticker = f"{backtest_ticker_input.strip()}{bt_suffix}".upper() # bt_suffix 沿用 tab1 邏輯
    
    st.markdown("#### 📅 選擇回測期間")
    period_option = st.selectbox("選擇歷史區間", ["近 3 年", "近 5 年", "🐻 2022 (熊市防禦測試)", "✍️ 自訂日期區間"])
    
    bt_start, bt_end, bt_days = None, None, 1825
    if period_option == "近 3 年": bt_days = 1095
    elif period_option == "近 5 年": bt_days = 1825
    elif period_option == "🐻 2022 (熊市防禦測試)": bt_start, bt_end = "2022-01-01", "2022-12-31"
    elif period_option == "✍️ 自訂日期區間":
        c_start, c_end = st.columns(2)
        with c_start: bt_start = st.date_input("開始", datetime.date(2022, 1, 1)).strftime("%Y-%m-%d")
        with c_end: bt_end = st.date_input("結束", datetime.date.today()).strftime("%Y-%m-%d")
    
    st.markdown("#### ⚙️ 資金與成本參數")
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1: init_cash = st.number_input("初始本金 (NTD)", value=1000000, step=100000)
    with col_c2: trade_size = st.slider("🟢 綠區出現時，每次投入資金比例 (%)", 5, 50, 10, help="例如設 10%，只要今天在綠區，就拿總本金的 10% 買進，直到現金扣完。")
    with col_c3: enable_fees = st.checkbox("計算交易成本", value=True)

    if st.button("🚀 開始「綠底抄底、紅底逃頂」回測", type="primary", use_container_width=True):
        with st.spinner(f"正在載入 {bt_ticker} 並運算區間數據..."):
            if bt_start and bt_end: df_bt = load_data(bt_ticker, start_date=bt_start, end_date=bt_end)
            else: df_bt = load_data(bt_ticker, days=bt_days)
                
            if df_bt.empty: st.error("⚠️ 無法取得資料。")
            else:
                # 使用簡化版指標運算，只算區間
                df_bt = calculate_indicators(df_bt)
                
                # 成本率
                buy_fee_rate = 0.001425 if enable_fees else 0.0
                sell_fee_rate = (0.001425 + 0.003) if enable_fees else 0.0

                cash = init_cash
                shares = 0
                trades = []
                execution_log = [] 
                equity_curve = []
                
                entry_price_avg = 0.0 
                total_cost_basis = 0.0 
                entry_date_first = None 

                for date, row in df_bt.iterrows():
                    price = row['Close']
                    zone_code = row['Zone_Code'] # Red=1, Green=-1, White=0

                    # ★ 新。區間賣出邏輯 (只要有持股，遇到紅區就清倉)
                    if zone_code == 1 and shares > 0:
                        sell_val_gross = shares * price
                        sell_fee = sell_val_gross * sell_fee_rate
                        sell_val_net = sell_val_gross - sell_fee
                        
                        total_invested_cash = total_cost_basis * (1 + buy_fee_rate)
                        profit = sell_val_net - total_invested_cash
                        ret_pct = (profit / total_invested_cash) * 100
                        
                        cash += sell_val_net
                        
                        # 流水帳
                        execution_log.append({'日期': date.strftime('%Y-%m-%d'), '動作': '🔴 紅區清倉', '成交價': round(price, 2), '股數': shares, '金額': round(sell_val_net, 0), '說明': '進入升溫區間'})
                        
                        # 趟數結算
                        trades.append({'首次買進': entry_date_first.strftime('%Y-%m-%d'), '清倉日期': date.strftime('%Y-%m-%d'), '均價': round(entry_price_avg, 2), '賣價': round(price, 2), '股數': shares, '淨報酬%': round(ret_pct, 2)})
                        
                        # 重置狀態
                        shares = 0; entry_price_avg = 0.0; total_cost_basis = 0.0; entry_date_first = None

                    # ★ 新。區間買進邏輯 (只要在綠區，且有錢，就每天加碼)
                    elif zone_code == -1 and cash > 0:
                        budget = init_cash * (trade_size / 100.0) # 拿總本金的 X% 買
                        can_spend = min(budget, cash)
                        
                        can_buy_shares = int(can_spend // (price * (1 + buy_fee_rate)))
                        
                        if can_buy_shares > 0:
                            cost_gross = can_buy_shares * price
                            cash -= (cost_gross * (1 + buy_fee_rate))
                            
                            if entry_date_first is None: entry_date_first = date
                            
                            # 更新攤平均價
                            total_cost_basis += cost_gross
                            shares += can_buy_shares
                            entry_price_avg = total_cost_basis / shares 
                            
                            execution_log.append({'日期': date.strftime('%Y-%m-%d'), '動作': '🟢 綠區抄底', '成交價': round(price, 2), '股數': can_buy_shares, '金額': -round(cost_gross * (1+buy_fee_rate), 0), '說明': f'價值抄底加碼'})

                    # 白區 holding，不用寫程式
                    current_equity = cash + (shares * price)
                    equity_curve.append(current_equity)

                df_bt['Equity'] = equity_curve

                # ★ 基準線重設計：同步改為「回測區間第一天」 All-in 買進並抱到尾 (Buy & Hold)
                buy_hold_shares = int(init_cash // (df_bt['Close'].iloc[0] * (1 + buy_fee_rate)))
                bh_rem_cash = init_cash - (buy_hold_shares * df_bt['Close'].iloc[0] * (1 + buy_fee_rate))
                bh_final_val = (buy_hold_shares * df_bt['Close'].iloc[-1] * (1 - sell_fee_rate)) + bh_rem_cash
                
                strategy_ret = ((df_bt['Equity'].iloc[-1] - init_cash) / init_cash) * 100
                bh_ret = ((bh_final_val - init_cash) / init_cash) * 100
                
                st.markdown("---")
                st.subheader(f"📊 區間回測報告：{bt_ticker}")
                
                m1, m2 = st.columns(2)
                m1.metric("🤖 區間存股策略總淨報酬", f"{strategy_ret:.2f}%", f"打敗傻傻抱著: {(strategy_ret - bh_ret):.2f}%")
                m2.metric("📈 傻傻抱著參考基準 (Buy & Hold)", f"{bh_ret:.2f}%")
                
                if execution_log:
                    trades_df = pd.DataFrame(trades)
                    df_bt['Peak'] = df_bt['Equity'].cummax()
                    max_dd = ((df_bt['Equity'] - df_bt['Peak']) / df_bt['Peak']).min() * 100

                    col_r1, col_r2 = st.columns(2)
                    col_r1.metric("🏆 交易趟數", f"{len(trades_df)} 趟")
                    col_r2.metric("📉 策略最大資金回撤 (MDD)", f"{max_dd:.2f}%")

                    # 資金曲線
                    fig_eq = go.Figure()
                    fig_eq.add_trace(go.Scatter(x=df_bt.index, y=df_bt['Equity'], line=dict(color='gold', width=2.5), name='區間存股資金曲線'))
                    bh_curve = (buy_hold_shares * df_bt['Close']) + bh_rem_cash
                    fig_eq.add_trace(go.Scatter(x=df_bt.index, y=bh_curve, line=dict(color='gray', dash='dot'), name='傻傻抱著基準線'))
                    fig_eq.update_layout(title="資金成長對比", height=450, hovermode="x unified")
                    st.plotly_chart(fig_eq, use_container_width=True)

                    with st.expander("🔍 查看每一筆「綠抄底、紅清倉」執行流水帳"):
                        st.dataframe(pd.DataFrame(execution_log), use_container_width=True)
                else:
                    st.warning("⚠️ 此區間無觸發買賣。")

# ------------------------------------------
# 分頁三：⚖️ 金庫儀表板 (★ 簡化)
# ------------------------------------------
with tab3: # 因移除選股 scanner，分頁變為 3 個
    st.header("⚖️ 雲端金庫 ＆ 大盤儀表板")
    if st.session_state.market_fetched:
        # 大盤儀表板沿用舊邏輯
        ms = st.session_state.market_scores
        def get_color(val, max_val): return "limegreen" if val >= max_val * 0.8 else ("crimson" if val <= max_val * 0.4 else "gold")
        col_g1, col_g2, col_g3, col_g4 = st.columns(4)
        with col_g1: st.plotly_chart(draw_gauge(ms['trend'], 40, ms['titles'][0], get_color(ms['trend'], 40)), use_container_width=True)
        with col_g2: st.plotly_chart(draw_gauge(ms['mom'], 20, ms['titles'][1], get_color(ms['mom'], 20)), use_container_width=True)
        with col_g3: st.plotly_chart(draw_gauge(ms['bias'], 20, ms['titles'][2], get_color(ms['bias'], 20)), use_container_width=True)
        with col_g4: st.plotly_chart(draw_gauge(ms['vix'], 20, ms['titles'][3], get_color(ms['vix'], 20)), use_container_width=True)
        
        st.markdown("---")
        st.markdown("### 💼 我的雲端庫存清單")
        df_h = st.session_state.user_holdings
        if not df_h.empty:
            summary = df_h.groupby('Ticker').agg({'Shares': 'sum', 'Total_Cost': 'sum', '目前股價': 'first'}).reset_index()
            summary['平均成本'] = (summary['Total_Cost'] / summary['Shares']).round(2)
            summary['目前市值'] = (summary['Shares'] * summary['目前股價']).round(0)
            summary['未實現損益%'] = (((summary['目前股價'] - summary['平均成本']) / summary['平均成本']) * 100).round(2)
            st.dataframe(summary, use_container_width=True)
        else: st.warning("金庫空空如也。")
