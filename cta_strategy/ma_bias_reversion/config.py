# API Keys
# 警告：請務必將您的金鑰存放在安全的地方，不要直接上傳到公開的程式碼庫。
API_KEY = "YOUR_API_KEY"
SECRET_KEY = "YOUR_SECRET_KEY"
MEMO = "YOUR_MEMO"

# --- 策略參數 ---

# 交易對 (請確保為 BitMart 合約支援的交易對)
SYMBOL = 'BTCUSDT'

# K線時間週期 (1, 3, 5, 15, 30, 60, 120, 240, 360, 720, 1440, 10080)
# 這裡我們用 15 分鐘
TIMEFRAME_MINUTES = 1

# 移動平均線 (MA) 的計算週期
MA_PERIOD = 20

# 乖離率 (BIAS) 開倉閾值
# BIAS = (價格 - MA) / MA
BIAS_ENTRY_LONG = -0.001  # -0.1% 時做多
BIAS_ENTRY_SHORT = 0.001   # +0.1% 時做空

# 止損百分比
STOP_LOSS_PERCENT = 0.02  # 2%

# 每次下單的合約數量 (單位: 張)
# 注意：請根據您的風險承受能力和帳戶資金調整
ORDER_SIZE = 1

# 槓桿倍數
LEVERAGE = '10'

# 倉位模式 (1: 逐倉, 2: 全倉)
MARGIN_MODE = 1

# 開倉類型 (isolated: 逐倉, cross: 全倉)
OPEN_TYPE = 'isolated'
