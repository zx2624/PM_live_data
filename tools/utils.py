import json
import logging
import os
import sys
import time
from typing import List

from agents.polymarket.gamma import GammaMarketClient as Gamma


def setup_logger(name, log_file=None, to_stdout=False):
    """
    Setup a logger with the specified name, log file, and stdout option.
    :param name: Name of the logger
    :param log_file: File to log messages to. If None, logs will not be saved to a file.
    :param to_stdout: If True, log messages will also be printed to stdout.
    :return: Configured logger instance
    """
    log_format = (
        "%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s"
    )
    formatter = logging.Formatter(log_format)
    # 创建一个Logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if to_stdout:
        # logger输出到控制台
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
    else:
        # loggger输出到控制台
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


default_logger = setup_logger("default_logger")


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
    :param tag_slug: the slug of the tag, e.g. "nba-uta-por"
    :param game_date: the date of the game, e.g. "2024-12-06"
    :return: a list of events that match the tag_slug and game_date
    """
    if tag_slug == "":
        return []
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
    team_mapping = {
        "Twolves": "Timberwolves",
    }
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
            if market["sportsMarketType"] != "moneyline":
                continue
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
                if outcome in team_mapping:
                    outcome = team_mapping[outcome]
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
    # Return a tuple (status_code, flip_rate)
    # status_code: 0 for normal, other codes for different invalid scenarios
    # flip_rate: the probability of the game outcome flipping

    # Check tie game first - Code 103
    if int(score_diff) == 0:
        logger.info("Score is tied, skip")
        return 103, 0.5  # 50% chance either team wins

    # Calculate flip_rate first, before other checks
    time_played_str = f"{time_played}"
    data_over_score_diff = df[(abs(df[time_played_str]) == abs(score_diff))].copy()

    # Calculate flip_rate if we have data
    if len(data_over_score_diff) > 0:
        # Use .loc instead of directly assigning to avoid SettingWithCopyWarning
        data_over_score_diff.loc[:, "product"] = data_over_score_diff.apply(
            lambda row: calculate_row_product(row, time_played_str), axis=1
        )
        fliped_games = data_over_score_diff[data_over_score_diff["product"] < 0]
        flip_rate = len(fliped_games) / len(data_over_score_diff)
        logger.info(
            (
                f"Fliped_rate: {flip_rate:.4f}, {len(fliped_games)} / "
                f"{len(data_over_score_diff)}"
            )
        )
    else:
        flip_rate = 0.0
        logger.info("No matching data found for flip rate calculation")

    # Now perform other checks, but return calculated flip_rate
    if time_played <= 2880 - 360:
        # early than Q4 10:00 - Code 101
        logger.info("Game too early, before Q4 10:00 mark")
        return 101, flip_rate

    if time_played >= 2880 - 2:
        # Too close to the end of the game - Code 102
        logger.info("Too close to the end of the game, skip")
        return 102, flip_rate

    # Not enough games for statistical significance - Code 104
    if len(data_over_score_diff) < 300:
        logger.info(
            f"Only {len(data_over_score_diff)} games, not enough to check flip rate"
        )
        return 104, flip_rate

    return 0, flip_rate  # Status code 0 means normal








# TODO: add calculate_sell_market_price


