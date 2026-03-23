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

st.sidebar.subheader("🛡️ 總體趨勢防護網 (防假突破)")
# ★ 新增：ADX 趨勢濾網，避免盤整時頻繁被雙巴
use_adx_filter = st.sidebar.checkbox("開啟【ADX 趨勢過濾】(極度推薦)", value=True, help="開啟後，只有當 ADX > 20 (趨勢明確) 時，才會觸發買點，大幅減少盤整期的頻繁假訊號。")

st.sidebar.markdown("---")

st.sidebar.subheader("🎯 買點設定 (進場攻擊)")
use_breakout = st.sidebar.checkbox("開啟【壓縮突破】買點 (桃紅向上)", value=True)
bbw_factor = st.sidebar.slider("布林壓縮容錯率 (建議：1.10)", min_value=1.0, max_value=1.5, value=1.1, step=0.05)
vol_factor = st.sidebar.slider("成交量爆發倍數 (建議：1.50)", min_value=1.0, max_value=3.0, value=1.5, step=0.1)

use_pullback = st.sidebar.checkbox("開啟【多頭拉回】買點 (綠色向上)", value=True)
kd_threshold = st.sidebar.slider("KD 金叉最高位階 (強勢股建議設50-60)", min_value=20, max_value=80, value=50, step=5)

use_ma_bounce = st.sidebar.checkbox("開啟【20MA 回踩】波段買點 (藍色向上)", value=True)
use_5ma_bounce = st.sidebar.checkbox("開啟【5MA 回踩】飆股買點 (黃色向上)", value=True)

st.sidebar.markdown("---")

st.sidebar.subheader("🛑 賣點設定 (出場防守)")
st.sidebar.write("*(強勢波段股建議只開黑箭頭與藍箭頭)*")
use_sell_5ma = st.sidebar.checkbox("開啟【跌破 5MA】極短線停利 (紅色向下)", value=True)
use_sell_kd = st.sidebar.checkbox("開啟【KD 高檔死叉】短線停利 (橘色向下)", value=True)
use_sell_rsi = st.sidebar.checkbox("開啟【RSI 跌破 70】過熱反轉 (紫色向下)", value=True)
use_sell_macd = st.sidebar.checkbox("開啟【MACD 死叉】波段轉弱 (藍色向下)", value=True)
use_sell_ma = st.sidebar.checkbox("開啟【跌破 20MA】中線停損 (黑色向下)", value=True)

st.sidebar.markdown("---")

# ==========================================
# 📊 核心運算函數
# ==========================================
@st.cache_data(ttl=3600)
def load_data(ticker, days=500): 
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=days)
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df

def calculate_indicators_and_signals(df, bbw_f, vol_f, kd_thresh, use_adx):
    if len(df) < 60: return df 
    
    # 均線與布林
    df['SMA_5'] = df['Close'].rolling(window=5).mean()
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_60'] = df['Close'].rolling(window=60).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
    df['Upper_Band'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['Lower_Band'] = df['SMA_20'] - (df['STD_20'] * 2)
    df['BBW'] = (df['Upper_Band'] - df['Lower_Band']) / df['SMA_20']
    
    # MACD & KD & RSI & OBV
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
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / ema_down
    df['RSI'] = 100 - (100 / (1 + rs))
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
    
    # ★ 計算 ADX 趨勢指標 (14天)
    df['Prev_Close'] = df['Close'].shift(1)
    df['TR'] = np.maximum(df['High'] - df['Low'], np.maximum(abs(df['High'] - df['Prev_Close']), abs(df['Low'] - df['Prev_Close'])))
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']), np.maximum(df['High'] - df['High'].shift(1), 0), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)), np.maximum(df['Low'].shift(1) - df['Low'], 0), 0)
    df['ATR_14'] = df['TR'].ewm(alpha=1/14, adjust=False).mean()
    df['+DI'] = 100 * (df['+DM'].ewm(alpha=1/14, adjust=False).mean() / df['ATR_14'])
    df['-DI'] = 100 * (df['-DM'].ewm(alpha=1/14, adjust=False).mean() / df['ATR_14'])
    df['DX'] = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = df['DX'].ewm(alpha=1/14, adjust=False).mean()

    # --- 買點判斷 (加入 ADX 濾網) ---
    adx_condition = (df['ADX'] > 20) if use_adx else True

    # 1. 壓縮突破
    df['Vol_5MA'] = df['Volume'].rolling(window=5).mean()
    df['Is_Squeeze'] = df['BBW'] <= df['BBW'].rolling(window=20).min() * bbw_f
    df['Squeeze_Recent'] = df['Is_Squeeze'].rolling(window=5).max().fillna(0) == 1
    df['Breakout'] = (df['Close'] > df['Upper_Band']) & (df['Volume'] > df['Vol_5MA'] * vol_f) & (df['Close'] > df['SMA_60'])
    df['Buy_Breakout'] = df['Squeeze_Recent'] & df['Breakout'] & adx_condition
    
    # 2. 多頭拉回 (KD 金叉)
    df['KD_Cross_Up'] = (df['K'] > df['D']) & (df['K'].shift(1) <= df['D'].shift(1))
    df['Buy_Pullback'] = df['KD_Cross_Up'] & (df['K'] <= kd_thresh) & (df['Close'] > df['SMA_60']) & adx_condition

    # 3. 均線回踩 (20MA)
    df['Bull_Trend'] = (df['SMA_5'] > df['SMA_20']) & (df['SMA_20'] > df['SMA_60'])
    df['Touch_20MA'] = df['Low'] <= (df['SMA_20'] * 1.015) 
    df['Close_Above_20MA'] = df['Close'] > df['SMA_20']    
    df['Green_Candle'] = df['Close'] > df['Open']          
    df['Buy_MABounce'] = df['Bull_Trend'] & df['Touch_20MA'] & df['Close_Above_20MA'] & df['Green_Candle'] & adx_condition

    # 4. 超級強勢股專用：5MA 沿線回踩
    df['Super_Bull'] = (df['SMA_5'] > df['SMA_20']) & (df['Close'] > df['SMA_20'])
    df['Touch_5MA'] = df['Low'] <= (df['SMA_5'] * 1.015)  
    df['Close_Above_5MA'] = df['Close'] > df['SMA_5']     
    df['Buy_5MABounce'] = df['Super_Bull'] & df['Touch_5MA'] & df['Close_Above_5MA'] & df['Green_Candle'] & adx_condition

    # --- 賣點判斷 ---
    df['Sell_5MA'] = (df['Close'] < df['SMA_5']) & (df['Close'].shift(1) >= df['SMA_5'].shift(1))
    df['Sell_KD'] = (df['K'] < df['D']) & (df['K'].shift(1) >= df['D'].shift(1)) & (df['K'].shift(1) >= 80)
    df['Sell_RSI'] = (df['RSI'] < 70) & (df['RSI'].shift(1) >= 70)
    df['Sell_MACD'] = (df['MACD'] < df['Signal']) & (df['MACD'].shift(1) >= df['Signal'].shift(1))
    df['Sell_MA20'] = (df['Close'] < df['SMA_20']) & (df['Close'].shift(1) >= df['SMA_20'].shift(1))
    
    return df

# ==========================================
# 🗂️ 建立分頁
# ==========================================
tab1, tab2 = st.tabs(["📊 個股詳細分析", "🚀 策略選股掃描器"])

with tab1:
    ticker_input = st.text_input("🔍 請輸入要分析的股票代碼 (例如: PL, MU, 2330.TW)", value="PL")
    df_raw = load_data(ticker_input, days=500) 
    
    if not df_raw.empty:
        df = calculate_indicators_and_signals(df_raw.copy(), bbw_factor, vol_factor, kd_threshold, use_adx_filter)
        fig = make_subplots(rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.04, 
                            row_heights=[0.4, 0.12, 0.12, 0.12, 0.12, 0.12],
                            subplot_titles=("K線與均線", "成交量 (Volume)", "KD 指標 (9)", "MACD 指標", "RSI 指標 (14)", "OBV 能量潮"))
        fig.update_annotations(x=0, xanchor="left", font_size=14, font_color="gray")
        
        # 主圖
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='red', decreasing_line_color='green'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash'), name='布林上軌'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='magenta', width=1.5), name='5MA(週)'), row=1, col=1) 
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1.5), name='20MA(月)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], line=dict(color='green', width=2), name='60MA(季)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='rgba(150, 150, 150, 0.5)', width=1, dash='dash'), name='布林下軌'), row=1, col=1)

        # 繪製買點
        if use_breakout:
            fig.add_trace(go.Scatter(x=df[df['Buy_Breakout']].index, y=df.loc[df['Buy_Breakout'], 'Low'] * 0.97, mode='markers', marker=dict(symbol='triangle-up', size=16, color='magenta', line=dict(width=1, color='DarkSlateGrey')), name='買：壓縮突破'), row=1, col=1)
        if use_pullback:
            fig.add_trace(go.Scatter(x=df[df['Buy_Pullback']].index, y=df.loc[df['Buy_Pullback'], 'Low'] * 0.95, mode='markers', marker=dict(symbol='triangle-up', size=14, color='lime', line=dict(width=1, color='DarkSlateGrey')), name='買：多頭拉回'), row=1, col=1)
        if use_ma_bounce:
            fig.add_trace(go.Scatter(x=df[df['Buy_MABounce']].index, y=df.loc[df['Buy_MABounce'], 'Low'] * 0.93, mode='markers', marker=dict(symbol='triangle-up', size=14, color='dodgerblue', line=dict(width=1, color='DarkSlateGrey')), name='買：20MA回踩'), row=1, col=1)
        if use_5ma_bounce:
            fig.add_trace(go.Scatter(x=df[df['Buy_5MABounce']].index, y=df.loc[df['Buy_5MABounce'], 'Low'] * 0.91, mode='markers', marker=dict(symbol='triangle-up', size=13, color='gold', line=dict(width=1, color='DarkSlateGrey')), name='買：5MA極強回踩'), row=1, col=1)

        # 繪製賣點
        if use_sell_5ma:
            fig.add_trace(go.Scatter(x=df[df['Sell_5MA']].index, y=df.loc[df['Sell_5MA'], 'High'] * 1.02, mode='markers', marker=dict(symbol='triangle-down', size=12, color='red', line=dict(width=1, color='DarkSlateGrey')), name='賣：破5MA'), row=1, col=1)
        if use_sell_kd:
            fig.add_trace(go.Scatter(x=df[df['Sell_KD']].index, y=df.loc[df['Sell_KD'], 'High'] * 1.04, mode='markers', marker=dict(symbol='triangle-down', size=12, color='orange', line=dict(width=1, color='DarkSlateGrey')), name='賣：KD死叉'), row=1, col=1)
        if use_sell_rsi:
            fig.add_trace(go.Scatter(x=df[df['Sell_RSI']].index, y=df.loc[df['Sell_RSI'], 'High'] * 1.06, mode='markers', marker=dict(symbol='triangle-down', size=12, color='purple', line=dict(width=1, color='DarkSlateGrey')), name='賣：RSI過熱'), row=1, col=1)
        if use_sell_macd:
            fig.add_trace(go.Scatter(x=df[df['Sell_MACD']].index, y=df.loc[df['Sell_MACD'], 'High'] * 1.08, mode='markers', marker=dict(symbol='triangle-down', size=12, color='blue', line=dict(width=1, color='DarkSlateGrey')), name='賣：MACD死叉'), row=1, col=1)
        if use_sell_ma:
            fig.add_trace(go.Scatter(x=df[df['Sell_MA20']].index, y=df.loc[df['Sell_MA20'], 'High'] * 1.10, mode='markers', marker=dict(symbol='triangle-down', size=14, color='black', line=dict(width=1, color='DarkSlateGrey')), name='賣：破月線'), row=1, col=1)

        # 副圖表
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

        fig.update_layout(height=1300, hovermode="x unified", dragmode='pan', showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1))
        
        dt_all = pd.date_range(start=df.index[0], end=df.index[-1])
        dt_breaks = [d.strftime("%Y-%m-%d") for d in dt_all if d not in df.index]
        fig.update_xaxes(rangebreaks=[dict(values=dt_breaks)], showspikes=True, spikemode='across', spikethickness=1, spikecolor='grey', spikedash='dot', rangeslider=dict(visible=False))
        fig.update_yaxes(showspikes=True, spikemode='across', spikethickness=1, spikecolor='grey', spikedash='dot', nticks=15)
        st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True, 'modeBarButtonsToAdd': ['drawline', 'drawrect', 'eraseshape']})
    else:
        st.error("查無資料，請確認股票代碼是否正確。")

with tab2:
    st.header("🚀 策略選股掃描器")
    scan_mode = st.radio("選擇掃描範圍：", ["🔥 預設精選", "👑 台灣 50 成分股", "🦅 美股科技巨頭", "✏️ 自訂輸入"])
    if scan_mode == "🔥 預設精選":
        pool = "0050.TW, 0056.TW, 2330.TW, 2317.TW, 2454.TW, 4958.TW, 2603.TW"
    elif scan_mode == "👑 台灣 50 成分股":
        pool = "2330.TW, 2317.TW, 2454.TW, 2382.TW, 2412.TW, 2881.TW, 2891.TW, 2882.TW, 2886.TW, 2884.TW, 1216.TW, 2002.TW, 3231.TW, 2308.TW, 2892.TW, 2885.TW, 3711.TW, 2890.TW, 5880.TW, 2303.TW, 2880.TW, 2887.TW, 1101.TW, 2883.TW, 2345.TW, 3045.TW, 3008.TW, 2912.TW, 2324.TW, 2603.TW, 1301.TW, 1303.TW, 2395.TW, 2801.TW, 6669.TW, 2357.TW, 3034.TW, 4904.TW, 1326.TW, 5871.TW, 2408.TW, 1102.TW, 2207.TW, 2379.TW, 1402.TW, 1590.TW, 6505.TW, 9904.TW, 2609.TW, 2615.TW"
    elif scan_mode == "🦅 美股科技巨頭":
        pool = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, AVGO, TSM, ASML, AMD, MU, INTC, QCOM, NFLX, PL"
    else:
        pool = st.text_area("自訂股票池", value="MU, NVDA, PL")

    if st.button("開始掃描", type="primary"):
        stock_list = [s.strip() for s in pool.split(",") if s.strip()]
        results = []
        progress = st.progress(0)
        for i, t in enumerate(stock_list):
            try:
                ds = load_data(t, days=150)
                if not ds.empty:
                    dc = calculate_indicators_and_signals(ds, bbw_factor, vol_factor, kd_threshold, use_adx_filter)
                    l = dc.iloc[-1]
                    
                    buy1 = use_breakout and l['Buy_Breakout']
                    buy2 = use_pullback and l['Buy_Pullback']
                    buy3 = use_ma_bounce and l['Buy_MABounce']
                    buy4 = use_5ma_bounce and l['Buy_5MABounce']
                    
                    if buy1 or buy2 or buy3 or buy4:
                        stype = []
                        if buy1: stype.append("🔥 壓縮突破")
                        if buy2: stype.append("🍀 多頭拉回")
                        if buy3: stype.append("🚀 20MA回踩")
                        if buy4: stype.append("⚡ 5MA極強回踩")
                        results.append({"代碼": t, "價錢": round(l['Close'], 2), "策略": " + ".join(stype)})
            except: pass
            progress.progress((i + 1) / len(stock_list))
        if results:
            st.success(f"發現 {len(results)} 檔符合條件")
            st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.warning("今日無符合買點條件股票")
