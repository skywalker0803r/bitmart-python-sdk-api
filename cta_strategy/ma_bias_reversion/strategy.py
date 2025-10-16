import time
import logging
import config
import os
import sys
import csv
from decimal import Decimal, getcontext
from datetime import datetime

# --- 路徑設定 ---
# 確保無論從哪裡執行，都能正確 import config 並找到日誌檔案
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from bitmart.api_contract import APIContract
from bitmart.lib.cloud_exceptions import APIException

# --- 初始化設定 ---
STATUS_FILE = os.path.join(SCRIPT_DIR, 'status.log')
TRADE_HISTORY_FILE = os.path.join(SCRIPT_DIR, 'trades.csv')

# 設定日誌記錄到檔案
log_file = os.path.join(SCRIPT_DIR, 'strategy.log')
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(log_file, mode='w'),
                        logging.StreamHandler() # 同時輸出到控制台
                    ])

# 設定 Decimal 運算精度
getcontext().prec = 10

def update_status(message):
    """將策略的即時狀態寫入檔案"""
    with open(STATUS_FILE, 'w') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {message}")

def log_trade(trade_data):
    """將完成的交易記錄到 CSV 檔案"""
    file_exists = os.path.isfile(TRADE_HISTORY_FILE)
    with open(TRADE_HISTORY_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            # 寫入標頭
            writer.writerow(['timestamp', 'symbol', 'side', 'amount', 'pnl', 'fee', 'notes'])
        writer.writerow([datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                         trade_data.get('symbol'),
                         trade_data.get('side'),
                         trade_data.get('amount'),
                         trade_data.get('pnl'),
                         trade_data.get('fee'),
                         trade_data.get('notes')])

class TradingStrategy:
    def __init__(self):
        """初始化策略"""
        logging.info("策略初始化...")
        if not hasattr(config, 'API_KEY') or config.API_KEY == "YOUR_API_KEY":
            logging.warning("偵測到預設 API 金鑰，將以僅讀模式運行。")
            self.api = APIContract(timeout=(10, 20))
            self.trade_enabled = False
        else:
            self.api = APIContract(config.API_KEY, config.SECRET_KEY, config.MEMO, timeout=(10, 20))
            self.trade_enabled = True
            self._prepare_trading_environment()

        self.symbol = config.SYMBOL
        self.kline_step = config.TIMEFRAME_MINUTES
        self.ma_period = config.MA_PERIOD
        self.last_kline_open_time = 0
        self.active_position = None # 用於追蹤當前持倉狀態

    def _prepare_trading_environment(self):
        if not self.trade_enabled: return
        try:
            logging.info(f"設定交易對 {self.symbol} 的槓桿為 {config.LEVERAGE}x")
            self.api.submit_leverage(symbol=self.symbol, leverage=config.LEVERAGE)
            self.cancel_all_plan_orders("首次運行清理")
        except APIException as e:
            logging.error(f"準備交易環境失敗: {e.response}")
            raise

    def check_trade_closure(self):
        """檢查倉位是否已關閉，並記錄交易"""
        if not self.trade_enabled or not self.active_position:
            return
        
        current_position = self.get_position()
        if not current_position:
            logging.info(f"倉位已關閉，記錄上一筆交易。原倉位方向: {self.active_position['side']}")
            update_status("倉位已關閉，正在記錄交易...")
            try:
                # 獲取最近的成交歷史
                history = self.api.get_transaction_history(self.symbol, type=2) # type=2 代表已實現盈虧
                if history[0]['code'] == 1000 and history[0]['data']:
                    last_trade = history[0]['data'][0]
                    log_trade({
                        'symbol': self.symbol,
                        'side': self.active_position['side'],
                        'amount': self.active_position['position_size'],
                        'pnl': last_trade.get('realised_pnl'),
                        'fee': last_trade.get('fee'),
                        'notes': f"TP/SL triggered. Closed at {last_trade.get('close_avg_price')}"
                    })
                else:
                    logging.warning("無法獲取成交歷史來記錄 PNL。")
                    log_trade({'notes': 'Position closed, but failed to fetch PNL history.'})
            except APIException as e:
                logging.error(f"獲取成交歷史失敗: {e.response}")
            finally:
                self.active_position = None # 清空倉位狀態
                self.cancel_all_plan_orders("倉位關閉後清理")

    def get_kline_data(self):
        try:
            limit = self.ma_period + 5
            end_time = int(time.time())
            start_time = end_time - (limit * self.kline_step * 60)
            response = self.api.get_kline(self.symbol, self.kline_step, start_time, end_time)
            if response[0]['code'] != 1000: return None
            klines = response[0]['data']
            klines.sort(key=lambda x: int(x['timestamp']))
            if int(klines[-1]['timestamp']) + self.kline_step * 60 > end_time: klines = klines[:-1]
            if len(klines) < self.ma_period: return None
            return klines
        except APIException as e:
            logging.error(f"API 請求 K 線時出錯: {e.response}")
            return None

    def calculate_indicators(self, klines):
        close_prices = [Decimal(k['close_price']) for k in klines]
        ma = sum(close_prices[-self.ma_period:]) / self.ma_period
        current_price = close_prices[-1]
        bias = (current_price - ma) / ma if ma != 0 else Decimal(0)
        return {"current_price": current_price, "ma": ma, "bias": bias}

    def get_position(self):
        if not self.trade_enabled: return None
        try:
            response = self.api.get_current_position(symbol=self.symbol)
            if response[0]['code'] != 1000 or not response[0]['data']: return None
            return response[0]['data'][0]
        except APIException as e:
            logging.error(f"API 請求倉位時出錯: {e.response}")
            return None

    def cancel_all_plan_orders(self, reason=""):
        if not self.trade_enabled: return
        try:
            logging.info(f"正在取消所有計畫委託... 原因: {reason}")
            self.api.cancel_all_plan_order(symbol=self.symbol)
        except APIException as e:
            if 'plan order not exists' not in str(e.response): logging.error(f"取消計畫委託失敗: {e.response}")

    def execute_trade_entry(self, side, indicators):
        if not self.trade_enabled: return
        update_status(f"偵測到信號，準備開倉 (Side: {side})...")
        try:
            logging.info(f"準備以市價開倉: side={side}, size={config.ORDER_SIZE}")
            response = self.api.new_order(symbol=self.symbol, side=side, type='market', size=config.ORDER_SIZE, mode=config.MARGIN_MODE, open_type=config.OPEN_TYPE)
            if response[0]['code'] != 1000: logging.error(f"開倉失敗: {response[0]['message']}"); return
            logging.info(f"開倉委託成功! Order ID: {response[0]['data']['order_id']}")
        except APIException as e: logging.error(f"API 開倉時出錯: {e.response}"); return

        time.sleep(3)
        position = self.get_position()
        if not position: logging.error("開倉後未能查詢到倉位，無法設定 TP/SL。"); return

        self.active_position = position # 記錄活動倉位
        open_price = Decimal(position['open_avg_price'])
        position_side = position['side']
        tp_price = indicators['ma']
        sl_price = open_price * (Decimal(1) - Decimal(config.STOP_LOSS_PERCENT)) if position_side == 'long' else open_price * (Decimal(1) + Decimal(config.STOP_LOSS_PERCENT))
        
        tp_price_str = f"{tp_price:.4f}"; sl_price_str = f"{sl_price:.4f}"
        logging.info(f"倉位開倉均價: {open_price:.4f}, 設定 TP: {tp_price_str}, SL: {sl_price_str}")
        update_status(f"持有 {position_side} 倉位, 開倉價: {open_price:.4f}, TP: {tp_price_str}, SL: {sl_price_str}")

        try:
            self.api.submit_tp_sl_order(symbol=self.symbol, order_type='tp', expected_price=tp_price_str, plan_type='normal')
            self.api.submit_tp_sl_order(symbol=self.symbol, order_type='sl', expected_price=sl_price_str, plan_type='normal')
            logging.info("TP/SL 計畫委託提交成功!")
        except APIException as e:
            logging.error(f"提交 TP/SL 計畫委託失敗: {e.response}")
            logging.info("將嘗試平倉以控制風險...")
            close_side = 2 if position_side == 'long' else 3
            self.api.new_order(symbol=self.symbol, side=close_side, type='market', size=config.ORDER_SIZE)

    def run(self):
        logging.info("策略開始運行...")
        while True:
            try:
                current_time = time.time()
                next_run_time = (current_time // (self.kline_step * 60) + 1) * (self.kline_step * 60)
                
                if self.last_kline_open_time >= next_run_time - (self.kline_step * 60): time.sleep(10); continue

                # 在進入主要邏輯前，先檢查倉位是否已關閉
                self.check_trade_closure()

                if not self.active_position:
                    sleep_duration = next_run_time - current_time
                    if sleep_duration > 0:
                        update_status(f"等待 {self.kline_step}m K線... (剩餘 {sleep_duration:.0f} 秒)")
                        time.sleep(sleep_duration)

                    update_status("獲取 K 線數據並計算指標...")
                    klines = self.get_kline_data()
                    if not klines: continue
                    
                    self.last_kline_open_time = int(klines[-1]['timestamp'])
                    indicators = self.calculate_indicators(klines)
                    logging.info(f"價格: {indicators['current_price']}, MA({self.ma_period}): {indicators['ma']:.4f}, BIAS: {indicators['bias']:.4%}")

                    if indicators['bias'] <= config.BIAS_ENTRY_LONG:
                        logging.info(f"偵測到做多信號 (BIAS <= {config.BIAS_ENTRY_LONG:.2%})，執行開倉。")
                        self.execute_trade_entry(side=4, indicators=indicators)

                    elif indicators['bias'] >= config.BIAS_ENTRY_SHORT:
                        logging.info(f"偵測到做空信號 (BIAS >= {config.BIAS_ENTRY_SHORT:.2%})，執行開倉。")
                        self.execute_trade_entry(side=1, indicators=indicators)
                else:
                    update_status(f"持有 {self.active_position['side']} 倉位，等待 TP/SL 觸發...")
                    time.sleep(60) # 持倉時，不需要頻繁檢查

            except KeyboardInterrupt:
                logging.info("接收到手動中斷信號，策略停止。")
                self.cancel_all_plan_orders("手動停止程序")
                break
            except Exception as e:
                logging.error(f"主循環發生未知錯誤: {e}", exc_info=True)
                update_status(f"發生嚴重錯誤: {e}")
                time.sleep(60)

if __name__ == "__main__":
    strategy = TradingStrategy()
    strategy.run()
