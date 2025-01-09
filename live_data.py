# Query nba.live.endpoints.scoreboard and  list games in localTimeZone
import json
import logging
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
from tools.utils import buy_in, check_flip, client, get_team_token, get_time_played

logger = logging.getLogger(__name__)
# # logger with file line and time
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s",
# )

price_limit = 0.998
sell_th = 0.85
game_date = "2025-01-08"
logger_file = f"logs/live_data_{game_date}_{time.time()}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(logger_file, mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
balance_split = 3
token_shares = Manager().dict()


def sell_when_too_low():
    while True:
        if len(token_shares) == 0:
            time.sleep(60)
            continue
        bookparams = [BookParams(token, SELL) for token in list(token_shares.keys())]
        prices = client.get_prices(bookparams)
        for token in token_shares:
            # shares = token_shares[token]
            if token not in prices:
                logger.warning(f"token {token} not in prices")
                continue
            # price = float(prices[token][SELL])
            # if price <= sell_th:
            # res = client.create_and_post_order(
            #     OrderArgs(price=0.99, size=410 , side=SELL, token_id=token_id)
            # )
            # print(res)
            # orderid = res["orderID"]
            # res = client.get_order("0x7849dae5bfcdcc59ea9c7440a9782089e1538b7e9248b74eba58771b151d6e74")  # noqa
            # print(res)
            # size_matched = res["size_matched"]


def buy_one_game(  # noqa
    game_id: str, gameid_token: Dict, qt_window: ThreadDisplayWindow
):
    home_team = gameid_token[game_id]["homeTeam"]["team"]
    away_team = gameid_token[game_id]["awayTeam"]["team"]
    home_token = gameid_token[game_id]["homeTeam"]["outcome_token_id"]
    away_token = gameid_token[game_id]["awayTeam"]["outcome_token_id"]
    match_up = f"{away_team}_{home_team}"  # noqa
    bought_str = ""
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
        except JSONDecodeError as e:
            logger.info(
                f"game {away_team} VS {home_team} not started {e}, sleep for 5 minutes"
            )  # noqa
            qt_window.print(
                match_up,
                f"game {away_team} VS {home_team} not started {e}, sleep for 5 minutes",
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
            if keyword in status_text and "END" not in status_text:
                to_check = True
                break
        for keyword in ["Half", "End", "pre", "Q1", "Q2"]:
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
            flip_rate = check_flip(time_played, away_team_score - home_team_score)
            info_str += f" flip rate: {flip_rate}"
            token_to_check = (
                away_token if away_team_score > home_team_score else home_token
            )  # noqa
            team_to_check = (
                away_team if away_team_score > home_team_score else home_team
            )  # noqa
            if flip_rate < 0.002 and bought_str == "":
                try:
                    _, price_pair = buy_in(
                        tokens=[token_to_check],
                        price_threshold=0.7,
                        price_limit=price_limit,
                        balance_split=balance_split,
                    )
                    bought_str = f"bought {team_to_check} at {price_pair} with flip_rate {flip_rate}"  # noqa
                except Exception as e:
                    logger.info(f"buying {away_team} vs. {home_team} fail: {e}")
        info_str = f"{info_str}\n {bought_str}"
        qt_window.print(match_up, info_str)
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


def kill_window():
    logger.info("===========kill window========")
    time.sleep(1)
    # sys.exit()


if __name__ == "__main__":  # noqa
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

    app.exec()
    for thread in threads:
        thread.join()
    logger.info("All game finished !")
