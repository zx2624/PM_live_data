import atexit
import random
import subprocess
import sys
import threading
import time
from threading import Lock


class TerminalPrinter:
    def __init__(self, num_threads):
        self.num_threads = num_threads
        self.print_lock = Lock()
        self.positions = {}

        # 隐藏光标
        self.hide_cursor()

        # 注册程序退出时显示光标
        atexit.register(self.show_cursor)

        # 清屏
        subprocess.run(["clear"])
        # 初始化打印区域
        print("\n" * (num_threads * 3))

    def hide_cursor(self):
        """隐藏终端光标"""
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

    def show_cursor(self):
        """显示终端光标"""
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def move_cursor(self, line):
        """移动光标到指定行"""
        sys.stdout.write(f"\033[{line};0H")
        sys.stdout.flush()

    def print_at_position(self, thread_id, message):
        """在指定位置打印消息"""
        with self.print_lock:
            # 计算该线程应该打印的行号
            if thread_id not in self.positions:
                self.positions[thread_id] = thread_id * 3 + 1

            line = self.positions[thread_id]
            # 移动光标
            self.move_cursor(line)
            # 清除当前行
            sys.stdout.write("\033[K")
            # 打印消息
            print(f"Thread-{thread_id}: {message}")
            sys.stdout.flush()


def worker(printer, thread_id):
    """工作线程函数"""
    for i in range(10):
        # 模拟一些工作
        time.sleep(random.uniform(0.5, 2))
        message = f"Processing step {i + 1}"
        printer.print_at_position(thread_id, message)


def main():
    try:
        num_threads = 4
        printer = TerminalPrinter(num_threads)
        threads = []

        # 创建并启动线程
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(printer, i))
            threads.append(t)
            t.start()

        # 等待所有线程完成
        for t in threads:
            t.join()

        # 移动光标到最后
        printer.move_cursor(num_threads * 3 + 1)
        print("\nAll threads completed!")

    except KeyboardInterrupt:
        # 确保在Ctrl+C时也能恢复光标
        printer.show_cursor()
        print("\nProgram terminated by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
