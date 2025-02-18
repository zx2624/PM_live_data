import json
import logging
import os
import sys
import time
from typing import List

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    MarketOrderArgs,
    OrderArgs,
    OrderBookSummary,
    OrderType,
)
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY, SELL

from agents.polymarket.gamma import GammaMarketClient as Gamma


def setup_logger(name, log_file=None):
    log_format = (
        "%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s"
    )
    formatter = logging.Formatter(log_format)
    # 创建一个Logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    # consol handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    if log_file:
        if not os.path.exists(os.path.dirname(log_file)):
            os.makedirs(os.path.dirname(log_file))
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


default_logger = setup_logger("default_logger")
host: str = "https://clob.polymarket.com"
chain_id: int = 137
load_dotenv()
key = os.getenv("POLYGON_WALLET_PRIVATE_KEY")
funder = os.getenv("FUNDER")
default_logger.info("creating client")
client = ClobClient(
    host, key=key, chain_id=chain_id, signature_type=1, funder=funder
)  #
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)
default_logger.info("client created")
# balance = client.get_balance_allowance(
#     params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
# )["balance"]
# balance = float(balance) / 1e6
# default_logger.info(f"balance: {balance}")


quater_map = {
    "Q3": 3,
    "Q4": 4,
    "OT": 4,  # pretend OT is 4th quater
    "2OT": 4,  # pretend 2OT is 4th quater
    "3OT": 4,  # pretend 3OT is 4th quater
}


def query_events(tag_slug: str, game_date: str) -> list:
    """
    query events according to tag_slug and game_date
    """
    gamma = Gamma()
    querystring_params = {
        "limit": 1000,
        "active": True,
        "closed": False,
        "related_tags": True,
        "tag_slug": tag_slug
        # "slug": "nba-uta-por-2024-12-06"
        # "tag_id": "1,745,100639"
    }
    events = gamma.get_events(querystring_params=querystring_params)
    print(f"len(events): {len(events)}")
    filtered_events = []
    for event in events:
        if "series" not in event:
            continue
        assert len(event["series"]) == 1
        if game_date in event["slug"]:
            filtered_events.append(event)
    print(f"len(events): {len(filtered_events)}")
    with open(f"assets/events_{tag_slug}_{game_date}.json", "w") as f:
        json.dump(filtered_events, f, indent=4)
    return filtered_events


def query_events_by_slug(slug: str) -> list:
    gamma = Gamma()
    querystring_params = {"slug": slug}
    events = gamma.get_events(querystring_params=querystring_params)
    return events


def get_team_token(game_date: str, tag_slug) -> dict:
    gamma = Gamma()
    querystring_params = {
        "limit": 1000,
        "active": True,
        "closed": False,
        "related_tags": True,
        "tag_slug": tag_slug,
    }
    events = gamma.get_events(querystring_params=querystring_params)
    filtered_events = []
    for event in events:
        if "series" not in event:
            continue
        assert len(event["series"]) == 1
        if game_date in event["slug"]:
            filtered_events.append(event)

    outcome_tokens = {}
    for event in filtered_events:
        for market in event["markets"]:
            # "outcomes": "[\"Magic\", \"76ers\"]",
            outcomes = (
                market["outcomes"]
                .replace("[", "")
                .replace("]", "")
                .replace('"', "")
                .split(", ")
            )
            clobTokenIds = (
                market["clobTokenIds"]
                .replace("[", "")
                .replace("]", "")
                .replace('"', "")
                .split(", ")
            )
            for outcome, clob_token_id in zip(outcomes, clobTokenIds):
                assert (
                    outcome not in outcome_tokens
                ), f"outcome: {outcome} already exists"
                outcome_tokens[outcome] = clob_token_id
    return outcome_tokens


def get_time_played(status_text):
    if status_text.startswith("END"):
        quater = status_text.split(" ")[1]
        quater = quater_map[quater]
        time_str = "0:00"
    else:
        quater, time_str = status_text.split(" ")[0], status_text.split(" ")[1]
        quater = quater_map[quater]
    if time_str.startswith(":"):
        time_left = float(time_str[1:])
    else:
        time_left = float(time_str.split(":")[0]) * 60 + float(time_str.split(":")[1])

    if quater in [3, 4]:
        time_played = quater * 12 * 60 - time_left
    else:
        time_played = 4 * 12 * 60 + (quater - 4) * 5 * 60 - time_left
    return int(time_played)


def calculate_row_product(row, time_played):
    # 找到每行的第一个和最后一个有效数字
    last_valid = row.last_valid_index()
    return row[time_played] * row[last_valid]


def check_flip(time_played, score_diff, df, logger: logging.Logger = default_logger):
    if time_played >= 2880 - 2:
        logger.info("too close to the end of the game, skip")
        return 100
    if int(score_diff) == 0:
        return 100
    time_played = f"{time_played}"
    data_over_score_diff = df[(abs(df[time_played]) == abs(score_diff))].copy()  #
    # only consider to check flip rate when there are more than 100 games
    if len(data_over_score_diff) < 300:
        logger.info(
            f"only {len(data_over_score_diff)} games, not enough to check flip rate"
        )
        return 100
    # check if time_played and last_score_diff have the same sign
    # current code has below warning, amend it
    # /home/zx/code/nba_api-master/tools/utils.py:96: SettingWithCopyWarning:
    # A value is trying to be set on a copy of a slice from a DataFrame.
    # Try using .loc[row_indexer,col_indexer] = value instead
    data_over_score_diff["product"] = data_over_score_diff.apply(
        lambda row: calculate_row_product(row, time_played), axis=1
    )
    fliped_games = data_over_score_diff[data_over_score_diff["product"] < 0]
    fliped_rate = len(fliped_games) / len(data_over_score_diff)
    logger.info(
        f"fliped_rate: {fliped_rate}, {len(fliped_games)} / {len(data_over_score_diff)}"
    )
    return fliped_rate


def sell_with_market_price(
    token: str, size: float, logger: logging.Logger = default_logger
):
    while True:
        logger.info(f"selling {token} with {size} shares")
        try:
            order = client.create_market_order(
                MarketOrderArgs(
                    token_id=token,
                    amount=size,
                    side=SELL,
                )
            )
            resp = client.post_order(order, orderType=OrderType.FOK)
            logger.info(f"sell {token} resp: {resp}")
        except PolyApiException as e:
            if "not enough balance" in str(e):
                logger.warning(f"sold out, with {e}")
                break
            elif "No orderbook exists" in str(e):
                logger.warning(f"No orderbook exists, with {e}")
                break
        except Exception as e:
            logger.error(f"sell {token} error: {e}")
            time.sleep(0.05)


def buy(
    token: str,
    price,
    price_threshold=0.9,
    price_limit=1.0,
    current_balance=0.0,
    logger: logging.Logger = default_logger,
):
    size = current_balance / price
    if price >= price_threshold and price < 1.0 and price <= price_limit:
        logger.info(f"Im buying {token} at {price} for {size} shares")
        try:
            res = client.create_and_post_order(
                OrderArgs(price=price, size=price_limit, side=BUY, token_id=token)
            )
            if "orderID" in res:
                orderid = res["orderID"]
                order_res = client.get_order(orderid)
                logger.info(f"{token} order_res: {order_res}")
            logger.info(f"{token} res: {res}")
            order_book = client.get_order_book(token)
            logger.info(f"{token} order_book: {order_book}")

        except PolyApiException as e:
            if "not enough balance" in str(e):
                logger.error("not enough balance, pretend I bought it")
                order_book = client.get_order_book(token)
                logger.info(f"{token} order_book: {order_book}")
                return True
            else:
                raise e


# TODO: add calculate_sell_market_price


def calculate_buy_market_price(
    order_book: OrderBookSummary,
    amount_to_match: float,
    logger: logging.Logger = default_logger,
) -> float:
    sum = 0.0
    positions = order_book.asks
    for p in reversed(positions):
        sum += float(p.size) * float(p.price)
        if sum >= amount_to_match:
            return float(p.price)
    logger.error(f"not enough liquidity to match {amount_to_match}")
    return -1


def buy_in(
    tokens,
    buy_price=None,
    price_threshold=0.9,
    price_limit=1.0,
    spread_th=None,
    buy_balance=0.0,
    logger: logging.Logger = default_logger,
):
    price_pair: List[float] = []
    for token in tokens:
        order_book: OrderBookSummary = client.get_order_book(token)
        if not buy_price:
            buy_price = calculate_buy_market_price(order_book, buy_balance, logger)
            if buy_price == -1:
                return False, price_pair, 0
        price_pair.append(buy_price)
        if (
            buy_price >= price_threshold
            and buy_price < 1.0
            and buy_price <= price_limit
        ):
            if spread_th:
                spread = float(client.get_spread(token)["spread"])
                if spread > spread_th:
                    logger.info(f"spread is {spread}, skip")
                    return False, price_pair, 0
            tick_size = float(client.get_tick_size(token))
            logger.info(f"tick_size is {tick_size}")
            size = round(buy_balance / buy_price, 2)
            logger.info(f"Im buying {token} at {buy_price} for {size} shares")
            try:
                expiration_stamp = int(time.time()) + 20 + 60
                order = client.create_order(
                    OrderArgs(
                        price=buy_price,
                        size=size,
                        side=BUY,
                        token_id=token,
                        expiration=expiration_stamp,
                    )
                )
                res = client.post_order(order, orderType=OrderType.GTD)
                logger.info(f"{token} post_order res: {res}")
                logger.info(f"{token} order_book: {order_book}")
                # sleep 10 s
                time.sleep(10)
            except PolyApiException as e:
                if "not enough balance" in str(e):
                    logger.error("not enough balance, pretend I bought it")
                    order_book = client.get_order_book(token)
                    logger.info(f"{token} order_book: {order_book}")
                    return False, price_pair, size
                else:
                    raise e

            # check order fill size
            orderid = res["orderID"]
            order_res = None
            while True:
                try:
                    order_res = client.get_order(orderid)
                except Exception:
                    continue
                if order_res and order_res["status"] != "LIVE":
                    break
                logger.info(f"{token} order still open with {order_res}")
                time.sleep(0.5)
            logger.info(f"{token} order_res: {order_res}")
            size = float(order_res["size_matched"])

            # return res

            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            with open("assets/buy_in.log", "a") as f:
                f.write(f"{token} {buy_price} {size} @{time_str}\n")
            return size > 0, price_pair, size
    return False, price_pair, 0
