import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

from agents.polymarket.gamma import GammaMarketClient as Gamma

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

host: str = "https://clob.polymarket.com"
chain_id: int = 137

load_dotenv()
key = os.getenv("POLYGON_WALLET_PRIVATE_KEY")
funder = os.getenv("FUNDER")
client = ClobClient(
    host, key=key, chain_id=chain_id, signature_type=1, funder=funder
)  #
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)
logger.info(creds)
balance = client.get_balance_allowance(
    params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
)["balance"]
balance = float(balance) / 1e6
# load csv
csv_path = Path(os.path.abspath(__file__)).parent.parent / "assets/fromq3"
csv_files = list(csv_path.glob("*.csv"))
df = pd.concat([pd.read_csv(file) for file in csv_files])

quater_map = {
    "Q3": 3,
    "Q4": 4,
    "OT": 5,
    "OT1": 5,
    "OT2": 6,
    "OT3": 7,
}


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
    logger.info(f"len(events): {len(filtered_events)}")

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


def check_flip(time_played, score_diff):
    if int(score_diff) == 0:
        return 100
    time_played = f"{time_played}"
    data_over_score_diff = df[(abs(df[time_played]) == abs(score_diff))].copy()  #
    # only consider to check flip rate when there are more than 100 games
    if len(data_over_score_diff) < 100:
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
    logger.info(f"fliped games: {len(fliped_games)}/{len(data_over_score_diff)}")
    fliped_rate = len(fliped_games) / len(data_over_score_diff)
    return fliped_rate


def buy_in(tokens, price_threshold=0.9):
    max_price = 0
    for token in tokens:
        price = float(client.get_price(token, SELL)["price"])
        logger.info(f"{token} current price is {price}")
        if price > max_price:
            max_price = price
        if price >= price_threshold and price < 1.0:
            tick_size = float(client.get_tick_size(token))
            logger.info(f"tick_size is {tick_size}")
            buy_price = min(price, 1.0 - tick_size)
            size = balance / buy_price
            logger.info(f"Im buying {token} at {buy_price} for {size} shares")
            res = client.create_and_post_order(
                OrderArgs(price=buy_price, size=size, side=BUY, token_id=token)
            )

            logger.info(res)
            # return res
            import time

            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            with open("assets/buy_in.log", "a") as f:
                f.write(f"{token} {buy_price} {size} @{time_str}\n")
            return True
    return False
