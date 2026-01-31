import logging
import sys
import threading
from typing import Dict

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ThreadPrinter(QObject):
    """用于线程打印的信号发射器"""

    print_signal = pyqtSignal(str, str, float, float)  # 参数：名称，打印内容，购买价格，当前价格

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def print(self, name: str, message: str, buy_price: float = -1, current_price: float = -1):
        """打印消息到指定名称的显示框
        
        Args:
            name: 显示框名称
            message: 显示内容
            buy_price: 购买价格，-1表示未购买
            current_price: 当前价格，-1表示未获取价格
        """
        self.print_signal.emit(name, message, buy_price, current_price)


class ThreadDisplayWindow(QMainWindow):
    """多线程显示窗口类"""

    def __init__(self, names: list[str]):
        super().__init__()
        self.names = names
        logger.info(f"names {names}")
        self.num_threads = len(names)
        self.message_labels: Dict[str, QLabel] = {}  # 存储显示标签的字典，使用名称作为键
        self.printer = ThreadPrinter()
        self.printer.print_signal.connect(self._handle_print)
        self.setup_ui()

    def setup_ui(self):
        """设置UI界面"""
        self.setWindowTitle("Thread Display")

        # 创建主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建主布局
        main_layout = QVBoxLayout(central_widget)

        # 根据线程数创建网格布局
        cols = min(4, self.num_threads)  # 最多4列
        rows = (self.num_threads + 1) // 4  # 计算需要的行数

        # 创建显示区域
        for row in range(rows + 1):
            row_layout = QHBoxLayout()
            for col in range(cols):
                idx = row * cols + col
                if idx < self.num_threads:
                    name = self.names[idx]
                    display_widget = self._create_display_widget(name)
                    row_layout.addWidget(display_widget)
            main_layout.addLayout(row_layout)

        # 设置窗口大小
        width = 300 * cols
        height = 100 * rows
        self.resize(width, height)

    def _create_display_widget(self, name: str) -> QWidget:
        """创建单个线程的显示部件"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 添加标题标签
        title = QLabel(name)
        title.setStyleSheet(
            """
            QLabel {
                font-weight: bold;
                color: #2c3e50;
                font-size: 14px;
            }
        """
        )
        layout.addWidget(title)

        # 添加消息显示标签
        message_label = QLabel("Waiting for messages...")
        message_label.setWordWrap(True)  # 允许文本换行
        message_label.setStyleSheet(
            """
            QLabel {
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 8px;
                min-height: 50px;
            }
        """
        )
        layout.addWidget(message_label)

        # 存储显示标签引用，使用名称作为键
        self.message_labels[name] = message_label

        return widget

    def _handle_print(self, name: str, message: str, buy_price: float, current_price: float):
        """处理打印请求"""
        if name in self.message_labels:
            label = self.message_labels[name]
            label.setText(message)  # 直接替换为最新消息
            
            # 根据价格设置背景颜色
            color = self._get_color_by_price(buy_price, current_price)
            label.setStyleSheet(
                f"""
                QLabel {{
                    background-color: {color};
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    padding: 8px;
                    min-height: 50px;
                }}
                """
            )
    
    def _get_color_by_price(self, buy_price: float, current_price: float) -> str:
        """根据购买价格和当前价格返回对应的颜色
        
        Args:
            buy_price: 购买价格，-1表示未购买
            current_price: 当前价格，-1表示未获取价格
            
        Returns:
            颜色代码字符串
        """
        # 未购买
        if buy_price < 0:
            return "white"
        
        # 已购买但未获取当前价格
        if current_price < 0:
            return "white"
        
        # 计算盈利情况
        diff = current_price - buy_price
        
        if abs(diff) < 0.001:  # 持平（考虑浮点数精度）
            return "#E6B3FF"  # 紫色
        elif diff > 0:  # 盈利
            return "#90EE90"  # 绿色
        else:  # 损失
            return "#FFB3B3"  # 红色

    def print(self, name: str, message: str, buy_price: float = -1, current_price: float = -1):
        """供外部调用的打印方法
        
        Args:
            name: 显示框名称
            message: 显示内容
            buy_price: 购买价格，-1表示未购买
            current_price: 当前价格，-1表示未获取价格
        """
        self.printer.print(name, message, buy_price, current_price)


# 使用示例
if __name__ == "__main__":
    import random
    import time

    def worker(name: str, window):
        """示例工作线程"""
        for i in range(10):
            message = f"Message {i}\nTimestamp: {time.strftime('%H:%M:%S')}"
            window.print(name, message)
            time.sleep(random.uniform(0.5, 2.0))

    # 创建应用
    app = QApplication(sys.argv)

    # 定义显示窗口的名称列表
    display_names = [
        "Temperature Sensor",
        "Humidity Sensor",
        "Pressure Monitor",
        "Light Sensor",
    ]

    # 创建显示窗口
    window = ThreadDisplayWindow(display_names)
    window.show()

    # 创建工作线程
    threads = []
    for name in display_names:
        thread = threading.Thread(target=worker, args=(name, window))
        threads.append(thread)
        thread.start()

    # 运行应用
    sys.exit(app.exec())
