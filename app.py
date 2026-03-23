import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import datetime

# 1. 網頁基本設定
st.set_page_config(page_title="專屬技術分析與量化選股系統", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# ⚙️ 左側邊欄：策略控制台
# ==========================================
st.sidebar.title("⚙️ 策略參數控制台")

st.sidebar.markdown("---")
st.sidebar.markdown("### 💡 分析師推薦實戰組合")
st.sidebar.info("""
**🟢 穩健波段流 (適合 0050, 大型權值股)**
* **買點全開：** 突破(桃紅) + 拉回(綠) + 20MA回踩(藍)
* **賣點只開：** MACD死叉(藍) + 破月線(黑)

**🔥 強勢飆股流 (適合 PL, MU, NVDA)**
* **買點只開：** 突破(桃紅) + 5MA回踩(黃)
* **賣點只開：** 破5MA(紅) + RSI過熱(紫)
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

st.sidebar.markdown("---")

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
    if df.empty:
        return df
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
    
    df['Hover_Text'] = (
        "20MA乖離率: " + df['Bias_20MA'].round(2).astype(str) + "%<br>" +
        "RSI (14): " + df['RSI'].round(1).astype(str) + "<br>" +
        "進場判定: <b>" + df['Status_Signal'] + "</b>"
    )
    
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
tab1, tab2, tab3 = st.tabs(["📊 個股詳細分析", "🚀 策略選股掃描器", "💰 策略回測實驗室"])

# ------------------------------------------
# 分頁一：個股詳細分析 (包含建倉計算機)
# ------------------------------------------
with tab1:
    ticker_input_raw = st.text_input("🔍 請輸入要分析的股票代碼", value="2330.TW", key="tab1_input")
    ticker_input = ticker_input_raw.strip().upper()
    df_raw = load_data(ticker_input, days=1825) 
    
    if not df_raw.empty:
        stock_name = get_stock_name(ticker_input)
        st.markdown(f"## 📊 {stock_name} ({ticker_input})")
        df = calculate_indicators_and_signals(df_raw.copy(), bbw_factor, vol_factor, kd_threshold, use_adx_filter, cooldown_days, safe_bias_limit)
        
        # --- 計算方塊獲利邏輯 ---
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
                        'buy_date': entry_d, 'buy_price': entry_p, 
                        'sell_date': exit_d, 'sell_price': exit_p, 
                        'return': ret, 'diff': diff, 'sell_high': df['High'].iloc[i], 'atr': df['ATR_14'].iloc[i]
                    })
        # ------------------------

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # ==========================================
        # ★ 新增：實戰建倉計算機 (風險平價模型)
        # ==========================================
        st.markdown("### 🧮 實戰建倉計算機 (風險平價模型)")
        st.caption("透過控管單筆交易的最大虧損，由系統反推建議你該買多少股，讓你永遠不會因為一檔股票重傷本金。")
        
        col_calc1, col_calc2 = st.columns(2)
        with col_calc1:
            total_capital = st.number_input("🏦 目前可用總資金 (NTD)", min_value=10000, max_value=100000000, value=1000000, step=10000)
        with col_calc2:
            risk_pct = st.slider("⚠️ 單筆願意承受的最大總資金虧損 (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5, help="華爾街標準通常為 1% ~ 2%。這保證你看錯停損時，不會重傷本金。")

        risk_amount = total_capital * (risk_pct / 100.0)
        entry_price = latest['Close']
        stop_loss_price = latest['SMA_20'] # 以波段防守線 20MA 作為停損依據

        if entry_price > stop_loss_price:
            risk_per_share = entry_price - stop_loss_price
            shares_by_risk = int(risk_amount // risk_per_share)
            shares_by_cash = int(total_capital // entry_price)
            
            # 取兩者最小，保證不會超過總資金，也不會超過風險容忍度
            recommended_shares = min(shares_by_risk, shares_by_cash)
            invest_amount = recommended_shares * entry_price
            
            st.success(f"📈 **建議買進股數： {recommended_shares:,.0f} 股** (約 {recommended_shares/1000:.1f} 張)")
            st.info(f"👉 **目前進場價：** ${entry_price:.2f} ｜ **防守停損價 (20MA)：** ${stop_loss_price:.2f}")
            st.warning(f"💰 **預計動用資金：** ${invest_amount:,.0f} (佔總資金 {(invest_amount/total_capital)*100:.1f}%) ｜ **看錯停損時最多只會賠：** ${recommended_shares * risk_per_share:,.0f}")
        else:
            st.error(f"🚨 目前股價 (${entry_price:.2f}) 低於防守線 20MA (${stop_loss_price:.2f})，處於空頭弱勢區，建議 **【空手觀望，0 股】**！")
            
        st.markdown("---")

        st.markdown(f"### 🛡️ 今日戰情室：進場風險評估 (日期: {latest.name.strftime('%Y-%m-%d')})")
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("最新收盤價", f"{latest['Close']:.2f}", f"{(latest['Close'] - prev['Close']):.2f} ({((latest['Close'] - prev['Close']) / prev['Close']) * 100:.2f}%)")
        with col2: st.metric("與 20MA 乖離率", f"{latest['Bias_20MA']:.2f}%")
        with col3: st.metric("RSI (14)", f"{latest['RSI']:.1f}")
        
        status_color = "🟢" if "安全" in latest['Status_Signal'] else "🟡" if "留意" in latest['Status_Signal'] else "🔴" if "危險" in latest['Status_Signal'] else "⚫"
        with col4: st.markdown(f"**判定**<br><span style='font-size:20px'>{latest['Status_Signal']}</span>", unsafe_allow_html=True)
        st.markdown("---")
        
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

        fig.update_layout(height=1300, hovermode="x unified", dragmode='pan', showlegend=False)
        default_start = df.index[-1] - pd.Timedelta(days=150)
        dt_breaks = [d.strftime("%Y-%m-%d") for d in pd.date_range(start=df.index[0], end=df.index[-1]) if d not in df.index]
        fig.update_xaxes(range=[default_start, df.index[-1] + pd.Timedelta(days=10)], rangebreaks=[dict(values=dt_breaks)], showspikes=True, spikemode='across', spikethickness=1, spikecolor='grey', spikedash='dot', rangeslider=dict(visible=False))
        fig.update_yaxes(showspikes=True, spikemode='across', spikethickness=1, spikecolor='grey', spikedash='dot', nticks=15)
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'modeBarButtonsToAdd': ['drawline', 'drawrect', 'eraseshape']})
    else:
        st.error("查無資料，請確認股票代碼是否正確。")

# ------------------------------------------
# 分頁二：策略選股掃描器
# ------------------------------------------
with tab2:
    st.header("🚀 策略選股掃描器")
    scan_mode = st.radio("選擇掃描範圍：", ["🔥 預設精選", "👑 台灣 50 成分股", "🌊 台灣熱門中大型 150 檔", "🦅 美股科技巨頭", "✏️ 自訂輸入"])
    if scan_mode == "🔥 預設精選":
        pool = "0050.TW, 0056.TW, 2330.TW, 2317.TW, 2454.TW, 4958.TW, 2603.TW"
    elif scan_mode == "👑 台灣 50 成分股":
        pool = "2330.TW, 2317.TW, 2454.TW, 2382.TW, 2412.TW, 2881.TW, 2891.TW, 2882.TW, 2886.TW, 2884.TW, 1216.TW, 2002.TW, 3231.TW, 2308.TW, 2892.TW, 2885.TW, 3711.TW, 2890.TW, 5880.TW, 2303.TW, 2880.TW, 2887.TW, 1101.TW, 2883.TW, 2345.TW, 3045.TW, 3008.TW, 2912.TW, 2324.TW, 2603.TW, 1301.TW, 1303.TW, 2395.TW, 2801.TW, 6669.TW, 2357.TW, 3034.TW, 4904.TW, 1326.TW, 5871.TW, 2408.TW, 1102.TW, 2207.TW, 2379.TW, 1402.TW, 1590.TW, 6505.TW, 9904.TW, 2609.TW, 2615.TW"
    elif scan_mode == "🌊 台灣熱門中大型 150 檔":
        pool = "1101.TW, 1102.TW, 1216.TW, 1301.TW, 1303.TW, 1326.TW, 1402.TW, 1590.TW, 2002.TW, 2207.TW, 2303.TW, 2308.TW, 2317.TW, 2324.TW, 2330.TW, 2345.TW, 2357.TW, 2379.TW, 2382.TW, 2395.TW, 2408.TW, 2412.TW, 2454.TW, 2603.TW, 2609.TW, 2615.TW, 2801.TW, 2880.TW, 2881.TW, 2882.TW, 2883.TW, 2884.TW, 2885.TW, 2886.TW, 2887.TW, 2890.TW, 2891.TW, 2892.TW, 2912.TW, 3008.TW, 3034.TW, 3045.TW, 3231.TW, 3711.TW, 4904.TW, 4938.TW, 4958.TW, 5871.TW, 5880.TW, 6505.TW, 6669.TW, 9904.TW, 1504.TW, 1536.TW, 1605.TW, 1717.TW, 1722.TW, 1802.TW, 1907.TW, 2049.TW, 2059.TW, 2105.TW, 2301.TW, 2313.TW, 2344.TW, 2352.TW, 2353.TW, 2356.TW, 2362.TW, 2371.TW, 2376.TW, 2377.TW, 2383.TW, 2385.TW, 2392.TW, 2404.TW, 2409.TW, 2449.TW, 2451.TW, 2504.TW, 2606.TW, 2610.TW, 2618.TW, 2727.TW, 2809.TW, 2812.TW, 2834.TW, 2845.TW, 2851.TW, 2903.TW, 2915.TW, 3019.TW, 3037.TW, 3044.TW, 3443.TW, 3481.TW, 3532.TW, 3702.TW, 4961.TW, 5522.TW, 6176.TW, 6239.TW, 6285.TW, 8046.TW, 8454.TW, 8464.TW, 9910.TW, 9914.TW, 9921.TW, 9933.TW, 9938.TW, 9939.TW, 9941.TW, 9945.TW"
    elif scan_mode == "🦅 美股科技巨頭":
        pool = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, AVGO, TSM, ASML, AMD, MU, INTC, QCOM, NFLX, PL"
    else:
        pool = st.text_area("自訂股票池", value="2330.TW, 0050.TW")

    if st.button("開始掃描", type="primary"):
        stock_list = [s.strip().upper() for s in pool.split(",") if s.strip()]
        results = []
        progress = st.progress(0)
        for i, t in enumerate(stock_list):
            try:
                ds = load_data(t, days=150)
                if not ds.empty:
                    dc = calculate_indicators_and_signals(ds, bbw_factor, vol_factor, kd_threshold, use_adx_filter, cooldown_days, safe_bias_limit)
                    l = dc.iloc[-1]
                    buy1 = use_breakout and l['Buy_Breakout']
                    buy2 = use_pullback and l['Buy_Pullback']
                    buy3 = use_ma_bounce and l['Buy_MABounce']
                    buy4 = use_5ma_bounce and l['Buy_5MABounce']
                    
                    if buy1 or buy2 or buy3 or buy4:
                        c_name = get_stock_name(t)
                        stype = []
                        if buy1: stype.append("🔥 壓縮突破")
                        if buy2: stype.append("🍀 多頭拉回")
                        if buy3: stype.append("🚀 20MA回踩")
                        if buy4: stype.append("⚡ 5MA極強回踩")
                        results.append({"代碼": t, "名稱": c_name, "價錢": round(l['Close'], 2), "策略": " + ".join(stype), "進場風險": l['Status_Signal']})
            except: pass
            progress.progress((i + 1) / len(stock_list))
        if results:
            st.success(f"發現 {len(results)} 檔符合條件")
            st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.warning("今日無符合買點條件股票")

# ------------------------------------------
# 分頁三：策略回測實驗室 
# ------------------------------------------
with tab3:
    st.header("💰 策略回測實驗室 (實戰驗證)")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        backtest_ticker = st.text_input("🔍 請輸入要回測的股票代碼", value="2330.TW", key="tab3_input").strip().upper()
    with col_t2:
        backtest_period = st.selectbox("📅 選擇回測時光機", [
            "過去 1 年 (近期大牛市)", 
            "2022 全年 (經典大熊市)", 
            "過去 3 年 (經歷牛熊雙殺)",
            "過去 5 年 (長期考驗)"
        ])
    
    if st.button("開始執行回測", type="primary"):
        df_bt_raw = load_data(backtest_ticker, days=2200) 
        
        if not df_bt_raw.empty:
            df_bt_all = calculate_indicators_and_signals(df_bt_raw.copy(), bbw_factor, vol_factor, kd_threshold, use_adx_filter, cooldown_days, safe_bias_limit)
            
            if backtest_period == "過去 1 年 (近期大牛市)": df_bt = df_bt_all.last("365D").copy()
            elif backtest_period == "2022 全年 (經典大熊市)": df_bt = df_bt_all.loc['2022-01-01':'2022-12-31'].copy()
            elif backtest_period == "過去 3 年 (經歷牛熊雙殺)": df_bt = df_bt_all.last("1095D").copy()
            else: df_bt = df_bt_all.last("1825D").copy()
            
            df_bt['Combined_Buy'] = False
            if use_breakout: df_bt['Combined_Buy'] = df_bt['Combined_Buy'] | df_bt['Buy_Breakout']
            if use_pullback: df_bt['Combined_Buy'] = df_bt['Combined_Buy'] | df_bt['Buy_Pullback']
            if use_ma_bounce: df_bt['Combined_Buy'] = df_bt['Combined_Buy'] | df_bt['Buy_MABounce']
            if use_5ma_bounce: df_bt['Combined_Buy'] = df_bt['Combined_Buy'] | df_bt['Buy_5MABounce']
            
            df_bt['Combined_Sell'] = False
            if use_sell_5ma: df_bt['Combined_Sell'] = df_bt['Combined_Sell'] | df_bt['Sell_5MA']
            if use_sell_kd: df_bt['Combined_Sell'] = df_bt['Combined_Sell'] | df_bt['Sell_KD']
            if use_sell_rsi: df_bt['Combined_Sell'] = df_bt['Combined_Sell'] | df_bt['Sell_RSI']
            if use_sell_macd: df_bt['Combined_Sell'] = df_bt['Combined_Sell'] | df_bt['Sell_MACD']
            if use_sell_ma: df_bt['Combined_Sell'] = df_bt['Combined_Sell'] | df_bt['Sell_MA20']

            initial_capital = 1000000
            cash = initial_capital
            position = 0
            equity_curve = []
            trade_log = []
            
            win_trades = 0
            total_trades = 0
            entry_price = 0
            
            for i in range(len(df_bt)):
                current_date = df_bt.index[i]
                current_price = df_bt['Close'].iloc[i]
                
                if position > 0 and df_bt['Combined_Sell'].iloc[i]:
                    cash = position * current_price
                    total_trades += 1
                    if current_price > entry_price:
                        win_trades += 1
                    trade_log.append({"日期": current_date.strftime('%Y-%m-%d'), "動作": "🔴 賣出", "價格": round(current_price, 2), "資產餘額": round(cash, 0)})
                    position = 0
                
                elif position == 0 and df_bt['Combined_Buy'].iloc[i]:
                    position = cash / current_price
                    entry_price = current_price
                    trade_log.append({"日期": current_date.strftime('%Y-%m-%d'), "動作": "🟢 買進", "價格": round(current_price, 2), "資產餘額": round(cash, 0)})
                    cash = 0
                
                current_equity = cash + (position * current_price if position > 0 else 0)
                equity_curve.append(current_equity)
            
            df_bt['Strategy_Equity'] = equity_curve
            
            shares_bh = initial_capital / df_bt['Close'].iloc[0]
            df_bt['BuyHold_Equity'] = shares_bh * df_bt['Close']
            
            df_bt['Strategy_RollMax'] = df_bt['Strategy_Equity'].cummax()
            df_bt['Strategy_DD'] = (df_bt['Strategy_Equity'] - df_bt['Strategy_RollMax']) / df_bt['Strategy_RollMax']
            strategy_mdd = df_bt['Strategy_DD'].min() * 100
            
            df_bt['BH_RollMax'] = df_bt['BuyHold_Equity'].cummax()
            df_bt['BH_DD'] = (df_bt['BuyHold_Equity'] - df_bt['BH_RollMax']) / df_bt['BH_RollMax']
            bh_mdd = df_bt['BH_DD'].min() * 100
            
            final_strategy = df_bt['Strategy_Equity'].iloc[-1]
            final_bh = df_bt['BuyHold_Equity'].iloc[-1]
            strategy_ret = ((final_strategy - initial_capital) / initial_capital) * 100
            bh_ret = ((final_bh - initial_capital) / initial_capital) * 100
            win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
            
            st.markdown(f"### 📉 【{backtest_period}】 戰績總結")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("🤖 策略最終資產", f"${final_strategy:,.0f}", f"{strategy_ret:.2f}%")
                st.metric("策略最大痛苦指數 (MDD)", f"{strategy_mdd:.2f}%")
            with col_b:
                st.metric("🤡 死抱不放最終資產", f"${final_bh:,.0f}", f"{bh_ret:.2f}%")
                st.metric("死抱最大痛苦指數 (MDD)", f"{bh_mdd:.2f}%")
            with col_c:
                st.metric("總交易次數", f"{total_trades} 次")
                st.metric("交易勝率", f"{win_rate:.1f}%")
            
            fig_bt = go.Figure()
            fig_bt.add_trace(go.Scatter(x=df_bt.index, y=df_bt['Strategy_Equity'], mode='lines', name='🤖 你的策略資產', line=dict(color='magenta', width=3)))
            fig_bt.add_trace(go.Scatter(x=df_bt.index, y=df_bt['BuyHold_Equity'], mode='lines', name='🤡 死抱不放資產', line=dict(color='gray', dash='dash')))
            fig_bt.update_layout(title="資產成長曲線對比 (策略 vs 死抱)", yaxis_title="總資產 (NTD)", hovermode="x unified")
            st.plotly_chart(fig_bt, use_container_width=True)
            
            if trade_log:
                with st.expander("📝 點此查看所有歷史交易明細"):
                    st.dataframe(pd.DataFrame(trade_log), use_container_width=True)
            else:
                st.info("這段期間內沒有觸發任何交易。可以嘗試在左側放寬買點條件。")
