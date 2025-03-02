import os
import time
from typing import Dict

import certifi
from py_clob_client.clob_types import BookParams, OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

from tools.utils import (
    calculate_buy_market_price,
    client,
    get_team_token,
    sell_with_market_price,
    setup_logger,
)

os.environ["SSL_CERT_FILE"] = certifi.where()

date = "2025-02-25"
logger = setup_logger("token_monitor", f"logs/{date}/token_monitor.log")
game_token = get_team_token(game_date=date, tag_slug="nba")
token_infos = {
    token: {"team": team, "size": 100, "price": 1.0}
    for team, token in game_token.items()
}
loss_sell_th = 1.0
profit_sell_th = 1.0
buy_balance = 100


def _process_real_tokens(prices: Dict) -> None:
    """Process tokens and execute trades based on price conditions"""
    for token in list(token_infos.keys()):
        shares = round(token_infos[token]["size"], 2)
        ori_price = token_infos[token]["price"]
        team = token_infos[token]["team"]

        if token not in prices:
            logger.warning(f"token {token} not in prices")
            continue
        # TODO: use calculate market price
        price = float(prices[token])
        logger.info(
            f"{team} {token} shares: {shares}, ori_price: {ori_price}, current price: {price}"
        )

        if ori_price - price > loss_sell_th:
            logger.warning(
                f"price too low, sell {team} {token} at {price} for {shares} shares"
            )
            sell_with_market_price(token=token, size=shares, logger=logger)
            if token in token_infos:
                token_infos.pop(token)
        elif price - ori_price > profit_sell_th:
            logger.info(
                f"enough profit, sell {team} {token} at {price} for {shares} shares"
            )
            sell_with_market_price(token=token, size=shares, logger=logger)
            if token in token_infos:
                token_infos.pop(token)


def price_monitor() -> None:
    """Monitor prices and execute trades based on conditions"""
    side = BUY
    while True:
        if len(token_infos) == 0:
            logger.info("no token to sell, sleep for 60 seconds")
            time.sleep(60)
            continue

        bookparams = [BookParams(token, side) for token in list(token_infos.keys())]

        try:
            time_now = time.time()
            # order_books = client.get_order_books(bookparams, timeout=1.0)
            # prices = {
            #     order_book.asset_id: calculate_buy_market_price(
            #         order_book, buy_balance, logger=logger
            #     )
            #     for order_book in order_books
            # }
            prices = client.get_prices(bookparams, timeout=0.1)
            prices = {token: float(prices[token][side]) for token in prices}
            logger.info(f"get prices in {time.time() - time_now} seconds")
            _process_real_tokens(prices)
        except Exception as e:
            logger.error(f"error when processing: {e}")


if __name__ == "__main__":
    price_monitor()
