# Query nba.live.endpoints.scoreboard and  list games in localTimeZone
import json
import logging
import sys
import threading
import time
from datetime import datetime
from json.decoder import JSONDecodeError
from typing import Dict

import pytz
from PyQt6.QtWidgets import QApplication
from requests.exceptions import ReadTimeout

from nba_api.live.nba.endpoints import boxscore
from nba_api.stats.endpoints import ScoreboardV2
from nba_api.stats.static import teams
from tools.qt_printer import ThreadDisplayWindow
from tools.utils import buy_in, check_flip, get_team_token, get_time_played

logger = logging.getLogger(__name__)
# logger with file line and time
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


# get game_date time_now in us tz
eastern = pytz.timezone("US/Eastern")
game_date = datetime.now(eastern).strftime("%Y-%m-%d")
logger.info(f"game_date now in us: {game_date}")
price_limit = 1.0


def buy_one_game(  # noqa
    game_id: str, gameid_token: Dict, qt_window: ThreadDisplayWindow
):
    home_team = gameid_token[game_id]["homeTeam"]["team"]
    away_team = gameid_token[game_id]["awayTeam"]["team"]
    tokens = [
        gameid_token[game_id]["homeTeam"]["outcome_token_id"],
        gameid_token[game_id]["awayTeam"]["outcome_token_id"],
    ]
    match_up = f"{away_team}_{home_team}"  # noqa
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
            if flip_rate < 0.002:
                try:
                    _, price_pair = buy_in(
                        tokens=tokens, price_threshold=0.8, price_limit=price_limit
                    )
                    qt_window.print(
                        match_up, f"bought at {price_pair} with flip_rate {flip_rate}"
                    )
                except Exception as e:
                    logger.info(f"buying {away_team} vs. {home_team} fail: {e}")
                break

        qt_window.print(match_up, info_str)

        if info["gameStatus"] == 3:
            logger.info(f"{game_id}: {away_team} vs. {home_team} finished")
            logger.info(f"score: {away_team_score} - {home_team_score}")
            try:
                buy_in(tokens=tokens, price_threshold=0.8, price_limit=price_limit)
            except Exception as e:
                logger.info(f"buy in finished game fail: {e}")
            break
        if not to_check:
            logger.info("no game to check, sleep for 5 minutes")
            time.sleep(300)
    logger.info(f"{away_team} vs. {home_team} finished")


if __name__ == "__main__":  # noqa
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
    if len(gameid_token) > 4:
        logger.info("enough games, change price limit")
        price_limit = 0.99
    logger.info(f"price_limit {price_limit}")
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
