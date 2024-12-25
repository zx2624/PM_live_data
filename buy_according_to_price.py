import json
import logging
import sys
import threading
import time
from datetime import datetime

import pytz
from py_clob_client.exceptions import PolyApiException
from PyQt6.QtWidgets import QApplication

from tools.qt_printer import ThreadDisplayWindow
from tools.utils import buy_in, query_events

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
total_threads = 10
price_threshold = 0.99
price_limit = 0.995
spread_th = 0.02


def buy_one(slug, token_pair, price_threshold=0.9, qt_window=None):
    time_price_list = []
    while True:
        time_stamp = time.time()
        try:
            bought, price_pair = buy_in(
                tokens=token_pair,
                price_threshold=price_threshold,
                price_limit=price_limit,
                spread_th=spread_th,
            )
            time_price_list.append((time_stamp, price_pair))
            logger.info(f"{slug}, price {price_pair}")
            qt_window.print(slug, f"price {price_pair}")
            if bought:
                logger.info(f"buy in {slug} done with price {price_pair}, close")
                qt_window.print(slug, f"bought at {price_pair}")
                break
        except PolyApiException as e:
            logger.error(f"{slug} PolyApiException error: {e}")
            if "not enough balance" in str(e):
                logger.error("not enough balance, close")
                qt_window.print(slug, "not enough balance")
                break
        except Exception as e:
            logger.error(f"{slug} error: {e}")
        time.sleep(total_threads / 10)
    with open(f"assets/prices/{slug}_{token_pair[0]}_{token_pair[1]}", "w") as f:
        for time_stamp, price_pair in time_price_list:
            f.write(f"{time_stamp} {price_pair[0]:.6} {price_pair[1]}\n")


if __name__ == "__main__":
    # 创建应用
    app = QApplication(sys.argv)
    slug_token_pairs = {}
    tag_slug = "nfl"
    eastern = pytz.timezone("US/Eastern")
    game_date = datetime.now(eastern).strftime("%Y-%m-%d")
    events = query_events(tag_slug, game_date)
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
