"""
定时调度脚本：凌晨3点启动 live_data.py，下午3点关闭
"""
import subprocess
import time
import signal
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

CUR_DIR = Path(__file__).parent

# 配置时间（24小时制）
START_HOUR = 3   # 凌晨3点启动
STOP_HOUR = 15   # 下午3点关闭


class LiveDataScheduler:
    def __init__(self):
        self.process = None
        self.running = True
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        print(f"\n[{self._now()}] 收到退出信号，正在清理...")
        self.running = False
        self.stop_live_data()
        sys.exit(0)
    
    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def start_live_data(self):
        """启动 live_data.py"""
        if self.process is not None and self.process.poll() is None:
            print(f"[{self._now()}] live_data.py 已经在运行中")
            return
        
        script_path = CUR_DIR / "live_data.py"
        print(f"[{self._now()}] 正在启动 live_data.py...")
        
        # 使用当前 Python 解释器启动脚本
        self.process = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(CUR_DIR),
            # 在 Windows 上创建新的进程组
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
        )
        print(f"[{self._now()}] live_data.py 已启动，PID: {self.process.pid}")
    
    def stop_live_data(self):
        """停止 live_data.py"""
        if self.process is None:
            print(f"[{self._now()}] 没有运行中的进程")
            return
        
        if self.process.poll() is not None:
            print(f"[{self._now()}] 进程已经结束")
            self.process = None
            return
        
        print(f"[{self._now()}] 正在停止 live_data.py (PID: {self.process.pid})...")
        
        try:
            if os.name == 'nt':
                # Windows: 发送 CTRL_BREAK_EVENT
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                # Unix: 发送 SIGTERM
                self.process.terminate()
            
            # 等待进程结束，最多等待30秒
            try:
                self.process.wait(timeout=30)
                print(f"[{self._now()}] live_data.py 已正常停止")
            except subprocess.TimeoutExpired:
                print(f"[{self._now()}] 进程未响应，强制终止...")
                self.process.kill()
                self.process.wait()
                print(f"[{self._now()}] live_data.py 已强制终止")
        except Exception as e:
            print(f"[{self._now()}] 停止进程时出错: {e}")
        finally:
            self.process = None
    
    def is_process_running(self):
        """检查进程是否在运行"""
        return self.process is not None and self.process.poll() is None
    
    def get_next_start_time(self):
        """计算下一次启动时间"""
        now = datetime.now()
        next_start = now.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
        if now >= next_start:
            next_start += timedelta(days=1)
        return next_start
    
    def get_next_stop_time(self):
        """计算下一次停止时间"""
        now = datetime.now()
        next_stop = now.replace(hour=STOP_HOUR, minute=0, second=0, microsecond=0)
        if now >= next_stop:
            next_stop += timedelta(days=1)
        return next_stop
    
    def should_be_running(self):
        """根据当前时间判断程序是否应该在运行"""
        current_hour = datetime.now().hour
        if START_HOUR < STOP_HOUR:
            # 同一天内：凌晨3点到下午3点
            return START_HOUR <= current_hour < STOP_HOUR
        else:
            # 跨天：比如晚上10点到第二天早上6点
            return current_hour >= START_HOUR or current_hour < STOP_HOUR
    
    def run(self):
        """主循环"""
        print(f"[{self._now()}] 调度器启动")
        print(f"  - 启动时间: 每天 {START_HOUR:02d}:00")
        print(f"  - 停止时间: 每天 {STOP_HOUR:02d}:00")
        print(f"  - 下次启动: {self.get_next_start_time()}")
        print(f"  - 下次停止: {self.get_next_stop_time()}")
        print()
        
        # 如果当前时间在运行区间内，立即启动
        if self.should_be_running():
            print(f"[{self._now()}] 当前时间在运行区间内，立即启动...")
            self.start_live_data()
        
        last_check_hour = -1
        
        while self.running:
            current_hour = datetime.now().hour
            
            # 只在小时变化时检查，避免重复操作
            if current_hour != last_check_hour:
                last_check_hour = current_hour
                
                # 凌晨3点启动
                if current_hour == START_HOUR:
                    if not self.is_process_running():
                        self.start_live_data()
                
                # 下午3点停止
                elif current_hour == STOP_HOUR:
                    if self.is_process_running():
                        self.stop_live_data()
            
            # 检查进程状态
            if self.should_be_running() and not self.is_process_running():
                if self.process is not None:
                    # 进程意外退出，重新启动
                    print(f"[{self._now()}] 检测到进程意外退出，正在重启...")
                    self.process = None
                    self.start_live_data()
            
            # 每分钟检查一次
            time.sleep(60)
        
        print(f"[{self._now()}] 调度器退出")


if __name__ == "__main__":
    scheduler = LiveDataScheduler()
    scheduler.run()

