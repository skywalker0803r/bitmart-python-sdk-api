import sys
import os
import json
import subprocess
import csv
import time

# --- 常數設定 ---
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STRATEGY_DIR = os.path.join(ROOT_DIR, 'cta_strategy')
RUNNING_PROCS_FILE = os.path.join(ROOT_DIR, '.running_strategies.json')

# --- 輔助函式 ---

def discover_strategies():
    """掃描 cta_strategy 資料夾，找出所有可用的策略"""
    strategies = []
    for name in os.listdir(STRATEGY_DIR):
        path = os.path.join(STRATEGY_DIR, name)
        if os.path.isdir(path) and 'strategy.py' in os.listdir(path):
            strategies.append(name)
    return strategies

def get_running_procs():
    """讀取正在運行的策略進程資訊"""
    if not os.path.exists(RUNNING_PROCS_FILE):
        return {}
    with open(RUNNING_PROCS_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_running_procs(procs):
    """儲存正在運行的策略進程資訊"""
    with open(RUNNING_PROCS_FILE, 'w') as f:
        json.dump(procs, f, indent=4)

def is_process_running(pid):
    """檢查進程是否仍在運行"""
    try:
        # os.kill(pid, 0) 在 Windows 上會直接終止進程，這裡改用 tasklist
        cmd = f'tasklist /FI "PID eq {pid}"'
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return str(pid) in str(output)
    except subprocess.CalledProcessError:
        return False # 命令執行失敗，通常意味著進程不存在

# --- 指令函式 ---

def start_strategy():
    """啟動一個策略"""
    strategies = discover_strategies()
    running_procs = get_running_procs()

    print("--- 可用策略 ---")
    available_to_start = []
    for i, name in enumerate(strategies):
        if name in running_procs:
            print(f"  {i + 1}. {name} (正在運行)")
        else:
            print(f"  {i + 1}. {name}")
            available_to_start.append(name)
    
    if not available_to_start:
        print("\n沒有可啟動的新策略。")
        return

    try:
        choice = int(input("\n請選擇要啟動的策略編號: ")) - 1
        strategy_name = strategies[choice]

        if strategy_name in running_procs:
            print(f"錯誤: 策略 '{strategy_name}' 已經在運行中。")
            return

        strategy_path = os.path.join(STRATEGY_DIR, strategy_name, 'strategy.py')
        
        # 使用 Popen 在背景啟動策略
        # 注意：日誌會寫入策略資料夾內的 strategy.log
        proc = subprocess.Popen([sys.executable, strategy_path])
        
        running_procs[strategy_name] = {'pid': proc.pid, 'start_time': time.time()}
        save_running_procs(running_procs)
        print(f"成功啟動策略 '{strategy_name}' (PID: {proc.pid})。")

    except (ValueError, IndexError):
        print("錯誤: 無效的選擇。")
    except Exception as e:
        print(f"啟動失敗: {e}")

def stop_strategy():
    """停止一個策略"""
    running_procs = get_running_procs()
    if not running_procs:
        print("沒有正在運行的策略。")
        return

    print("--- 正在運行的策略 ---")
    running_list = list(running_procs.keys())
    for i, name in enumerate(running_list):
        print(f"  {i + 1}. {name} (PID: {running_procs[name]['pid']})")

    try:
        choice = int(input("\n請選擇要停止的策略編號: ")) - 1
        strategy_name = running_list[choice]
        pid_to_kill = running_procs[strategy_name]['pid']

        print(f"正在停止策略 '{strategy_name}' (PID: {pid_to_kill})...")
        # 使用 taskkill 強制終止進程
        subprocess.run(f"taskkill /F /PID {pid_to_kill}", shell=True, check=True, capture_output=True)
        
        del running_procs[strategy_name]
        save_running_procs(running_procs)
        print(f"策略 '{strategy_name}' 已停止。")

    except (ValueError, IndexError):
        print("錯誤: 無效的選擇。")
    except subprocess.CalledProcessError as e:
        print(f"停止進程失敗: {e.stderr.decode('cp950', errors='ignore')}")
    except Exception as e:
        print(f"停止失敗: {e}")

def show_status():
    """顯示策略狀態"""
    running_procs = get_running_procs()
    if not running_procs:
        print("沒有正在運行的策略。")
        return

    print("--- 策略即時狀態 ---")
    procs_to_remove = []
    for name, info in running_procs.items():
        pid = info['pid']
        print(f"\n策略: {name} (PID: {pid})")
        if not is_process_running(pid):
            print("  狀態: [已停止] - 進程不存在，可能是意外終止。")
            procs_to_remove.append(name)
            continue

        status_file = os.path.join(STRATEGY_DIR, name, 'status.log')
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status = f.read().strip()
                print(f"  狀態: {status}")
        else:
            print("  狀態: 正在初始化或尚未回報狀態...")
    
    # 清理已停止的進程記錄
    if procs_to_remove:
        for name in procs_to_remove:
            del running_procs[name]
        save_running_procs(running_procs)
        print("\n已清理無效的策略記錄。")

def show_history():
    """顯示策略的歷史績效"""
    strategies = discover_strategies()
    if not strategies:
        print("找不到任何策略。")
        return

    print("--- 選擇策略以查看歷史績效 ---")
    for i, name in enumerate(strategies):
        print(f"  {i + 1}. {name}")

    try:
        choice = int(input("\n請選擇策略編號: ")) - 1
        strategy_name = strategies[choice]
        history_file = os.path.join(STRATEGY_DIR, strategy_name, 'trades.csv')

        if not os.path.exists(history_file):
            print(f"策略 '{strategy_name}' 沒有任何交易紀錄。")
            return

        print(f"\n--- '{strategy_name}' 交易歷史 ---")
        total_pnl = 0
        trade_count = 0
        with open(history_file, 'r') as f:
            reader = csv.reader(f)
            header = next(reader) # 跳過標頭
            print(f"{header[0]:<20} {header[2]:<5} {header[4]:>10} {header[5]:>10}")
            print("-"*50)
            for row in reader:
                trade_count += 1
                pnl = float(row[4]) if row[4] else 0
                total_pnl += pnl
                print(f"{row[0]:<20} {row[2]:<5} {pnl:>10.4f} {row[5]:>10}")
        
        print("-"*50)
        print(f"總交易次數: {trade_count}")
        print(f"總盈虧: {total_pnl:.4f}")

    except (ValueError, IndexError):
        print("錯誤: 無效的選擇。")
    except Exception as e:
        print(f"讀取歷史紀錄時發生錯誤: {e}")

def show_help():
    """顯示幫助訊息"""
    print("""
    可用指令:
      start     - 啟動一個新的策略。
      stop      - 停止一個正在運行的策略。
      status    - 查看正在運行的策略的即時狀態。
      history   - 查看一個策略的歷史交易紀錄與績效。
      help      - 顯示此幫助訊息。
      exit      - 退出 CLI。
    """)

def show_banner_and_help():
    """顯示酷炫的橫幅和幫助訊息"""
    banner = r"""
    ____                 _         _____         _     _           
   / __ \               | |       |_   _|       | |   | |          
  | |  | |_ __   ___  __| |   __ _  | |   _ __  | | __| | ___ _ __ 
  | |  | | '_ \ / _ \/ _` |  / _` | | |  | '_ \ | |/ _` |/ _ \ '__|
  | |__| | |_) |  __/ (_| | | (_| | | |  | | | || | (_| |  __/ |   
   \____/| .__/ \___|\__,_|  \__,_| |_|  |_| |_||_|
\__,_\___|_|   
         | |                                                      
         |_|                  CLI v1.0 - Happy Trading
    """
    print(banner)
    show_help()

# --- 主循環 ---

def main():
    """CLI 主程式"""
    show_banner_and_help()
    while True:
        try:
            command = input("\n(quant-cli) >>> ").strip().lower()
            if command == 'start':
                start_strategy()
            elif command == 'stop':
                stop_strategy()
            elif command == 'status':
                show_status()
            elif command == 'history':
                show_history()
            elif command == 'help':
                show_help()
            elif command == 'exit':
                print("正在退出...")
                # 可以在此處加入停止所有策略的邏輯
                break
            else:
                print(f"未知指令: '{command}'。輸入 'help' 查看可用指令。")
        except KeyboardInterrupt:
            print("\n接收到中斷信號，正在退出...")
            break

if __name__ == "__main__":
    main()