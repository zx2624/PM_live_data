import json
import logging
import sys
import threading
import time

from PyQt6.QtWidgets import QApplication

from tools.qt_printer import ThreadDisplayWindow
from tools.utils import buy_in

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
total_threads = 10
price_threshold = 0.99
price_limit = 0.995


def buy_one(slug, token_pair, price_threshold=0.9, qt_window=None):
    time_price_list = []
    while True:
        time_stamp = time.time()
        try:
            bought, price_pair = buy_in(
                tokens=token_pair,
                price_threshold=price_threshold,
                price_limit=price_limit,
            )
            time_price_list.append((time_stamp, price_pair))
            logger.info(f"{slug}, price {price_pair}")
            qt_window.print(slug, f"price {price_pair}")
            if bought:
                logger.info(f"buy in {slug} done with price {price_pair}, close")
                qt_window.print(slug, f"bought at {price_pair}")
                break
        except Exception as e:
            logger.error(f"{slug} error: {e}")
            pass
        time.sleep(total_threads / 10)
    with open(f"assets/prices/{slug}_{token_pair[0]}_{token_pair[1]}", "w") as f:
        for time_stamp, price_pair in time_price_list:
            f.write(f"{time_stamp} {price_pair[0]:.6} {price_pair[1]}\n")


if __name__ == "__main__":
    # 创建应用
    app = QApplication(sys.argv)
    slug_token_pairs = {}
    events_file = "/home/zx/code/nba_api/assets/events_nfl_2024-12-22.json"
    with open(events_file, "r") as f:
        events = json.load(f)
    for event in events:
        for market in event["markets"]:
            # token pair str in "[\"token1, token2\"]"
            slug = market["slug"]
            token_pair = json.loads(market["clobTokenIds"])
            slug_token_pairs[slug] = token_pair
    total_threads = len(slug_token_pairs)
    qt_window = ThreadDisplayWindow(list(slug_token_pairs.keys()))
    qt_window.show()
    # multithread with token pairs
    threads = []
    for slug in slug_token_pairs:
        # buy_one(slug, slug_token_pairs[slug], price_threshold, qt_window)
        thread = threading.Thread(
            target=buy_one,
            args=(slug, slug_token_pairs[slug], price_threshold, qt_window),
        )
        thread.start()
        threads.append(thread)
    sys.exit(app.exec())
    for thread in threads:
        thread.join()
