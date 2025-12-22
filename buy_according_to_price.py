import json
import logging
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from multiprocessing import Manager
from typing import Dict, List, Tuple

import certifi
from py_clob_client.clob_types import BookParams, OrderArgs
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY, SELL
from PyQt6.QtWidgets import QApplication

from tools.qt_printer import ThreadDisplayWindow
from src.agents.polymarket.polymarket import Polymarket
from tools.utils import (
    query_events,
    query_events_by_slug,
    setup_logger,
)

tag_slug = "nba"
game_date = "2025-02-27"
slugs = ["germany-parliamentary-election"]
slugs = [""]
loss_sell_th = 0.2
profit_sell_th = 0.03
price_threshold = 0.95
price_limit = 0.998
spread_th = 0.01
buy_balance = 1.0


class TradingSystem:
    def __init__(
        self,
        tag_slug: str = None,
        slugs: List[str] = None,
        game_date: str = "2025-02-22",
        loss_sell_th: float = 0.2,
        profit_sell_th: float = 0.004,
        price_threshold: float = 0.995,
        price_limit: float = 0.998,
        spread_th: float = 0.01,
        buy_balance: float = 100.0,
    ):
        # Initialize SSL certificate
        os.environ["SSL_CERT_FILE"] = certifi.where()

        # Initialize Polymarket client
        self.polymarket = Polymarket()

        # Trading parameters
        self.tag_slug = tag_slug
        self.game_date = game_date
        self.loss_sell_th = loss_sell_th
        self.profit_sell_th = profit_sell_th
        self.price_threshold = price_threshold
        self.price_limit = price_limit
        self.spread_th = spread_th
        self.buy_balance = buy_balance

        # Setup multiprocessing manager and shared dict
        self.manager = Manager()
        self.token_infos = self.manager.dict()

        # Setup logging
        self.logger = self._setup_logger()

        # Initialize events and slugs
        self.events = []
        self.slugs = slugs
        self.token_slug = {}
        self.slug_token_pairs = {}

        # UI window
        self.qt_window = None

    def _setup_logger(self) -> logging.Logger:
        """Setup logger with appropriate file name"""
        logger_file = f"logs/{self.game_date}/buy_according_price.log"
        return setup_logger("buy_according_price", logger_file)

    def initialize_events(self) -> None:
        """Initialize events and related data structures"""
        if self.tag_slug:
            self.events = query_events(self.tag_slug, self.game_date)
        for slug in self.slugs:
            self.events.extend(query_events_by_slug(slug))

        # Process events to create token mappings
        for event in self.events:
            for market in event["markets"]:
                slug = market["slug"]
                token_pair = json.loads(market["clobTokenIds"])
                self.slug_token_pairs[slug] = token_pair
                self.token_slug[token_pair[0]] = slug
                self.token_slug[token_pair[1]] = slug

        self.logger.info(f"slug_token_pairs: {self.slug_token_pairs}")
        self.logger.info(f"token_slug: {self.token_slug}")

    def _process_real_tokens(self, prices: Dict, side: str) -> None:
        """Process tokens and execute trades based on price conditions"""
        for token in list(self.token_infos.keys()):
            shares = round(self.token_infos[token]["size"], 2)
            ori_price = self.token_infos[token]["price"]
            team = self.token_infos[token]["team"]

            if token not in prices:
                self.logger.warning(f"token {token} not in prices")
                continue
            # TODO: use calculate market price
            price = float(prices[token][side])
            self.logger.info(
                f"{team} {token} shares: {shares}, ori_price: {ori_price}, current price: {price}"
            )

            if ori_price - price > self.loss_sell_th:
                self.logger.warning(
                    f"price too low, sell {team} {token} at {price} for {shares} shares"
                )
                self.polymarket.sell_with_market_price(token=token, size=shares, logger=self.logger)
                if token in self.token_infos:
                    self.token_infos.pop(token)
            elif price - ori_price > self.profit_sell_th:
                self.logger.info(
                    f"enough profit, sell {team} {token} at {price} for {shares} shares"
                )
                self.polymarket.sell_with_market_price(token=token, size=shares, logger=self.logger)
                if token in self.token_infos:
                    self.token_infos.pop(token)

    def price_monitor(self) -> None:
        """Monitor prices and execute trades based on conditions"""
        side = BUY
        while True:
            if len(self.token_infos) == 0:
                self.logger.info("no token to sell, sleep for 60 seconds")
                time.sleep(60)
                continue

            bookparams = [
                BookParams(token, side) for token in list(self.token_infos.keys())
            ]

            try:
                # TODO: use calculate market price
                prices = client.get_prices(bookparams)
                self._process_real_tokens(prices, side)
            except Exception as e:
                self.logger.error(f"error when processing: {e}")

    def buy_in_thread(self, token_slug: Dict, bookparams: List[BookParams]) -> None:
        """Execute buy orders in a separate thread"""
        slug_bought_str = {}

        while True:
            slug_prices = defaultdict(list)
            slug_spread = {}

            try:
                order_books = self.polymarket.client.get_order_books(bookparams)
                prices = {
                    order_book.asset_id: self.polymarket.calculate_buy_market_price(
                        order_book, self.buy_balance, logger=self.logger
                    )
                    for order_book in order_books
                }
                order_books = {
                    order_book.asset_id: order_book for order_book in order_books
                }
                spreads = client.get_spreads(bookparams)
            except PolyApiException as e:
                self.logger.error(f"PolyApiException error: {e}")
                continue

            possible_token_price_slug = self._analyze_market_conditions(
                token_slug,
                order_books,
                prices,
                spreads,
                slug_bought_str,
                slug_prices,
                slug_spread,
            )

            self._display_market_info(slug_prices, slug_spread)

            self._execute_buy_orders(
                possible_token_price_slug, order_books, slug_bought_str
            )

    def _analyze_market_conditions(
        self,
        token_slug: Dict,
        order_books: Dict,
        prices: Dict,
        spreads: Dict,
        slug_bought_str: Dict,
        slug_prices: Dict,
        slug_spread: Dict,
    ) -> List[Tuple]:
        """Analyze market conditions and return possible trading opportunities"""
        possible_token_price_slug = []

        for token, slug in token_slug.items():
            if token not in order_books:
                if token in self.token_infos:
                    self.logger.warning(f"token {token} not in order_books, pop it")
                    self.token_infos.pop(token)
                continue
            if any(
                [slug in slug_bought_str, token not in prices, token not in spreads]
            ):
                continue

            price = float(prices[token])
            spread = float(spreads[token])
            slug_prices[slug].append(price)
            slug_spread[slug] = spread

            if (
                self.price_threshold <= price <= self.price_limit
                and price < 1.0
                and spread <= self.spread_th
            ):
                possible_token_price_slug.append((token, price, slug))

        return sorted(possible_token_price_slug, key=lambda x: x[1])

    def _display_market_info(self, slug_prices: Dict, slug_spread: Dict) -> None:
        """Display market information in the UI and logs"""
        for slug in slug_prices.keys():
            assert len(slug_prices[slug]) == 2
            price_str = "_".join([f"{price:.6}" for price in slug_prices[slug]])
            price_str += f" spread {slug_spread[slug]:.6}"
            self.logger.info(f"{slug}, {price_str}")
            self.qt_window.print(slug, f"{price_str}")

    def _execute_buy_orders(
        self,
        possible_token_price_slug: List[Tuple],
        order_books: Dict,
        slug_bought_str: Dict,
    ) -> bool:
        """Execute buy orders for possible trading opportunities"""
        for token, price, slug in possible_token_price_slug:
            size = self.buy_balance / price
            bought_str = f"bought {slug} {token} at {price:.6} for {size:.6} shares"

            try:
                bought, bought_size = self.polymarket.buy(
                    token=token, buy_price=price, size=size, logger=self.logger
                )
                if bought and bought_size > 0:
                    self.logger.info(f"{token} order_book: {order_books[token]}")
                    slug_bought_str[slug] = bought_str
                    self.token_infos[token] = self.manager.dict()
                    self.token_infos[token]["size"] = bought_size
                    self.token_infos[token]["price"] = price
                    self.token_infos[token]["team"] = slug
            except Exception as e:
                self.logger.error(f"error when buying: {e}")
                continue

            self.logger.info(bought_str)
            self.qt_window.print(slug, bought_str)

    def run(self) -> None:
        """Main method to run the trading system"""
        # Setup signal handling
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        # Initialize QT application
        app = QApplication(sys.argv)

        # Initialize events and data structures
        self.initialize_events()

        # Setup UI
        self.qt_window = ThreadDisplayWindow(list(self.slug_token_pairs.keys()))
        self.qt_window.show()

        # Setup trading parameters
        bookparams = [BookParams(token, SELL) for token in self.token_slug.keys()]

        # Start trading threads
        buy_thread = threading.Thread(
            target=self.buy_in_thread, args=(self.token_slug, bookparams)
        )
        buy_thread.start()

        # Start price monitoring thread
        price_thread = threading.Thread(target=self.price_monitor)
        price_thread.start()

        # Run QT application
        app.exec()
        sys.exit()


if __name__ == "__main__":
    trading_system = TradingSystem(
        tag_slug=tag_slug,
        slugs=slugs,
        game_date=game_date,
        loss_sell_th=loss_sell_th,
        profit_sell_th=profit_sell_th,
        price_threshold=price_threshold,
        price_limit=price_limit,
        spread_th=spread_th,
        buy_balance=buy_balance,
    )
    trading_system.run()
