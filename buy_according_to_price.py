import json
import logging
import sys
import threading
import time
from collections import defaultdict

from py_clob_client.clob_types import BookParams, OrderArgs
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY, SELL
from PyQt6.QtWidgets import QApplication

from tools.qt_printer import ThreadDisplayWindow
from tools.utils import query_events_by_slug  # noqa
from tools.utils import balance, buy_in, client, query_events  # noqa

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
total_threads = 10
price_threshold = 0.995
price_limit = 0.998
spread_th = 0.03
balance_split = 1.0


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
            price_str = "_".join([f"{price:.6}" for price in price_pair])
            logger.info(f"{slug}, price {price_str}")
            qt_window.print(slug, f"price {price_str}")
            if bought:
                logger.info(f"buy in {slug} done with price {price_str}, close")
                qt_window.print(slug, f"bought at {price_str}")
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


def buy_in_thread(token_slug, bookparams, qt_window=None):
    slug_bought_str = ""
    while True:
        slug_prices = defaultdict(list)
        slug_spread = {}
        try:
            prices = client.get_prices(bookparams)
            spreads = client.get_spreads(bookparams)
        except PolyApiException as e:
            logger.error(f"PolyApiException error: {e}")
            continue
        possible_token_price_slug = []
        for token in token_slug.keys():
            slug = token_slug[token]
            price = float(prices[token][SELL])
            spread = float(spreads[token])
            slug_prices[slug].append(price)
            slug_spread[slug] = spread
            if (
                price >= price_threshold
                and price <= price_limit
                and price < 1.0
                and spread <= spread_th
            ):
                possible_token_price_slug.append((token, price, slug))
        for slug in slug_prices.keys():
            assert len(slug_prices[slug]) == 2
            price_str = "_".join([f"{price:.6}" for price in slug_prices[slug]])
            price_str += f" spread {slug_spread[slug]:.6}"
            logger.info(f"{slug}, {price_str}")
            qt_window.print(slug, f"{price_str}")
        # sort by price
        possible_token_price_slug.sort(key=lambda x: x[1])
        for token, price, slug in possible_token_price_slug:
            size = balance / balance_split / price
            bought_str = f"bought {slug} at {price:.6} for {size:.6} shares"
            logger.info(bought_str)
            qt_window.print(slug, bought_str)
            try:
                client.create_and_post_order(
                    OrderArgs(price=price, size=size, side=BUY, token_id=token)
                )
                order_book = client.get_order_book(token)
                logger.info(f"{token} order_book: {order_book}")
                slug_bought_str[slug] = bought_str
            except PolyApiException as e:
                if "not enough balance" in str(e):
                    logger.error("not enough balance, pretend I bought it")
                    logger.info(f"buy in {slug} {size} with price {price:.6}")
                    order_book = client.get_order_book(token)
                    logger.info(f"{token} order_book: {order_book}")
                    slug_bought_str[slug] = bought_str
                else:
                    raise e
        if len(slug_bought_str) == len(token_slug) // 2:
            logger.info("buy in all done")
            break


def kill_window():
    logger.info("===========kill window========")
    time.sleep(1)
    # sys.exit()


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # 创建应用
    app = QApplication(sys.argv)
    slug_token_pairs = {}
    tag_slug = "EPL"
    game_date = "2025-01-05"
    events = query_events(tag_slug, game_date)
    # slug = "will-bitcoin-hit-100k-again-in-2024-dec-23"
    # events = query_events_by_slug(slug)
    for event in events:
        for market in event["markets"]:
            # token pair str in "[\"token1, token2\"]"
            slug = market["slug"]
            token_pair = json.loads(market["clobTokenIds"])
            slug_token_pairs[slug] = token_pair
    logger.info(f"slug_token_pairs: {slug_token_pairs}")
    total_threads = len(slug_token_pairs)
    qt_window = ThreadDisplayWindow(list(slug_token_pairs.keys()))
    qt_window.show()
    # multithread with token pairs
    token_slug = {}
    for event in events:
        for market in event["markets"]:
            # token pair str in "[\"token1, token2\"]"
            slug = market["slug"]
            token_pair = json.loads(market["clobTokenIds"])
            token_slug[token_pair[0]] = slug
            token_slug[token_pair[1]] = slug
    bookparams = [BookParams(token, SELL) for token in token_slug.keys()]
    # two token one slug
    balance_split = len(token_slug) // 2
    logger.info(f"balance_split: {balance_split}")
    assert balance_split > 0
    thread = threading.Thread(
        target=buy_in_thread, args=(token_slug, bookparams, qt_window)
    )
    thread.start()
    app.exec()
    sys.exit()
