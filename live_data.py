# Query nba.live.endpoints.scoreboard and  list games in localTimeZone
import json
import sys
import threading
import time
from json.decoder import JSONDecodeError
from multiprocessing import Manager
from typing import Dict

from py_clob_client.clob_types import BookParams
from py_clob_client.order_builder.constants import SELL
from PyQt6.QtWidgets import QApplication
from requests.exceptions import ReadTimeout

from nba_api.live.nba.endpoints import boxscore
from nba_api.stats.endpoints import ScoreboardV2
from nba_api.stats.static import teams
from tools.qt_printer import ThreadDisplayWindow
from tools.utils import (
    buy_in,
    check_flip,
    client,
    get_team_token,
    get_time_played,
    sell_with_market_price,
    setup_logger,
)

price_limit = 0.998
loss_sell_th = 0.2  # sell when price decline more then 0.2$
profit_sell_th = 0.008  # sell when price increase more then 0.008$
game_date = "2025-02-08"
balance_split = 4
manager = Manager()
token_infos = manager.dict()


def sell_when_too_low():
    global token_infos
    logfile = f"logs/{game_date}/sell_when_too_low.log"
    logger = setup_logger("sell_when_too_low", logfile)
    while True:
        if len(token_infos) == 0:
            logger.info("no token to sell, sleep for 60 seconds")
            time.sleep(60)
            continue
        bookparams = [BookParams(token, SELL) for token in list(token_infos.keys())]
        try:
            prices = client.get_prices(bookparams)
        except Exception as e:
            logger.error(f"error when get prices: {e}")
            continue
        for token in token_infos:
            shares = round(token_infos[token]["size"], 2)
            ori_price = token_infos[token]["price"]
            team = token_infos[token]["team"]
            if token not in prices:
                logger.warning(f"token {token} not in prices")
                continue
            price = float(prices[token][SELL])
            logger.info(
                f"{team} {token} shares: {shares}, ori_price: {ori_price}, current price: {price}"  # noqa
            )
            if ori_price - price > loss_sell_th:
                logger.warning(
                    f"price too low, sell {team} {token} at {price} for {shares} shares !!!!"  # noqa
                )
                sell_with_market_price(token=token, size=shares, logger=logger)
                token_infos.pop(token)
            if price - ori_price > profit_sell_th:
                logger.info(
                    f"enough profit, sell {team} {token} at {price} for {shares} shares"
                )
                sell_with_market_price(token=token, size=shares, logger=logger)
                token_infos.pop(token)


def buy_one_game(  # noqa
    game_id: str, gameid_token: Dict, qt_window: ThreadDisplayWindow
):
    global token_infos
    home_team = gameid_token[game_id]["homeTeam"]["team"]
    away_team = gameid_token[game_id]["awayTeam"]["team"]
    home_token = gameid_token[game_id]["homeTeam"]["outcome_token_id"]
    away_token = gameid_token[game_id]["awayTeam"]["outcome_token_id"]
    match_up = f"{away_team}_{home_team}"  # noqa
    logfile = f"logs/{game_date}/{match_up}.log"
    logger = setup_logger(match_up, logfile)
    bought_str = ""
    fake_bought_str = ""  # some test
    while True:
        to_check = False
        try:
            box = boxscore.BoxScore(game_id, timeout=5)
            info = box.game.get_dict()  # equal to box.get_dict()["game"]
            assert (
                info["awayTeam"]["teamName"] == away_team
                and info["homeTeam"]["teamName"] == home_team
            ), "error, away team name not match"
        except ReadTimeout as e:
            logger.info(f"query {away_team} VS {home_team} timeout {e}")
            continue
        except JSONDecodeError:
            logger.info(
                f"game {away_team} VS {home_team} not started, sleep for 5 minutes"
            )  # noqa
            qt_window.print(
                match_up,
                f"game {away_team} VS {home_team} not started, sleep for 5 minutes",
            )  # noqa
            time.sleep(300)
            continue
        except Exception as e:
            logger.info(f"{away_team} VS {home_team}, some error {e}")
            continue

        home_team_score = info["homeTeam"]["score"]
        away_team_score = info["awayTeam"]["score"]
        status_text = info["gameStatusText"]
        status = info["gameStatus"]
        info_str = f"{away_team} {away_team_score} - {home_team} {home_team_score}  status: {status_text}"  # noqa
        for keyword in ["Q3", "Q4", "OT"]:
            if keyword in status_text:
                to_check = True
                break
        for keyword in ["Half", "pre", "Q1", "Q2"]:
            if keyword in status_text:
                logger.info(f"{away_team} vs. {home_team} {status_text}, sleeping")
                time.sleep(60)
        if to_check:
            # calculate time left Q4 6:29 or Q4 :29 or Q4 :00.9
            # try catch when testing, delete this when running
            try:
                time_played = get_time_played(status_text)
            except Exception as e:
                logger.info(f"error: {e} with {status_text} {status}")
                continue
            flip_rate = check_flip(
                time_played, away_team_score - home_team_score, logger=logger
            )
            info_str += f" flip rate: {flip_rate}"
            token_to_check = (
                away_token if away_team_score > home_team_score else home_token
            )  # noqa
            team_to_check = (
                away_team if away_team_score > home_team_score else home_team
            )  # noqa
            if flip_rate < 0.05 and fake_bought_str == "":
                bought, price_pair, size = buy_in(
                    tokens=[token_to_check],
                    price_threshold=1.0,
                    price_limit=0.0,
                    balance_split=balance_split,
                    logger=logger,
                )
                assert not bought, f"fake buy {team_to_check} fail"
                fake_bought_str = " ".join(
                    [
                        f"fake bought {team_to_check} for {size} shares",
                        f"at {price_pair} with flip_rate {flip_rate}",
                        f"{status_text}",
                        f"{away_team_score} - {home_team_score}",
                    ]
                )
                logger.info(fake_bought_str)

            if flip_rate < 0.005 and bought_str == "":
                logger.info(info_str)
                try:
                    bought, price_pair, size = buy_in(
                        tokens=[token_to_check],
                        price_threshold=0.7,
                        price_limit=price_limit,
                        balance_split=balance_split,
                        logger=logger,
                    )
                    bought_str = f"bought {team_to_check} for {size} shares at {price_pair} with flip_rate {flip_rate} {status_text}"  # noqa
                    if bought:
                        token_infos[token_to_check] = manager.dict()
                        token_infos[token_to_check]["size"] = size
                        token_infos[token_to_check]["price"] = price_pair[0]
                        token_infos[token_to_check]["team"] = team_to_check
                    else:
                        bought_str = f"not {bought_str}"
                    logger.info(bought_str)
                except Exception as e:
                    logger.info(f"buying {away_team} vs. {home_team} fail: {e}")
        qt_window.print(match_up, info_str + f" {bought_str}")
        logger.info(info_str)
        # TODO: check Q4 END
        if info["gameStatus"] == 3:
            logger.info(f"{game_id}: {away_team} vs. {home_team} finished")
            logger.info(f"score: {away_team_score} - {home_team_score}")
            # try:
            #     buy_in(tokens=tokens, price_threshold=0.8, price_limit=price_limit)
            # except Exception as e:
            #     logger.info(f"buy in finished game fail: {e}")
            break
    logger.info(f"{away_team} vs. {home_team} finished")


if __name__ == "__main__":  # noqa
    logfile = f"logs/{game_date}/main.log"
    logger = setup_logger("main", logfile)
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    # get team and token according to game_date
    team_token = get_team_token(game_date, "nba")
    # get games from nba_api.stats.endpoints.ScoreboardV2
    board = ScoreboardV2(game_date=game_date)
    data_sets = board.data_sets
    gameid_token = {}
    for data_set in data_sets:
        df = data_set.get_data_frame()
        if "GAME_ID" in df.columns and "HOME_TEAM_ID" in df.columns:
            df = df[["GAME_ID", "HOME_TEAM_ID", "VISITOR_TEAM_ID"]]
            # use game_id as key, home_team_id and visitor_team_id as values
            game_ids = df["GAME_ID"].values
            # assert len(game_ids) * 2 == len(
            #     team_token
            # ), f"error, team token should be double of game_ids, \
            #     got {len(game_ids)} game_ids and {len(team_token)} team tokens"
            for game_id in game_ids:
                home_team_id = df[df["GAME_ID"] == game_id]["HOME_TEAM_ID"].iloc[0]
                home_team = teams.find_team_name_by_id(home_team_id)["nickname"]
                if home_team not in team_token:
                    logger.info(f"{home_team} not in outcome_token_id")
                    continue
                visitor_team_id = df[df["GAME_ID"] == game_id]["VISITOR_TEAM_ID"].iloc[
                    0
                ]
                visitor_team = teams.find_team_name_by_id(visitor_team_id)["nickname"]
                # update gameid_token with team names
                gameid_token[game_id] = {
                    "homeTeam": {
                        "team": home_team,
                        "outcome_token_id": team_token[home_team],
                    },
                    "awayTeam": {
                        "team": visitor_team,
                        "outcome_token_id": team_token[visitor_team],
                    },
                }
            break
    logger.info(gameid_token)
    with open(f"assets/gameid_infos/gameid_token_{game_date}.json", "w") as f:
        json.dump(gameid_token, f, indent=4)
    logger.info(f"price_limit {price_limit}, balance_split {balance_split}")
    # terminal_printer = TerminalPrinter(len(gameid_token))
    threads = []
    window_names = []
    for game_id in gameid_token:
        home_team = gameid_token[game_id]["homeTeam"]["team"]
        away_team = gameid_token[game_id]["awayTeam"]["team"]
        match_up = f"{away_team}_{home_team}"
        window_names.append(match_up)
    qt_window = ThreadDisplayWindow(window_names)
    qt_window.show()
    for game_id in gameid_token:
        # buy_one_game(game_id, gameid_token)
        thread = threading.Thread(
            target=buy_one_game, args=(game_id, gameid_token, qt_window)
        )
        threads.append(thread)
        thread.start()
    sell_thread = threading.Thread(target=sell_when_too_low)
    sell_thread.start()
    threads.append(sell_thread)
    app.exec()
    for thread in threads:
        thread.join()
    logger.info("All game finished !")
