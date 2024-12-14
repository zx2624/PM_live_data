# Query nba.live.endpoints.scoreboard and  list games in localTimeZone
import json
import logging
import time
from datetime import datetime

import pytz

from nba_api.live.nba.endpoints import boxscore
from nba_api.stats.endpoints import ScoreboardV2
from nba_api.stats.static import teams
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

if __name__ == "__main__":
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
            assert len(game_ids) * 2 == len(
                team_token
            ), f"error, team token should be double of game_ids, \
                got {len(game_ids)} game_ids and {len(team_token)} team tokens"
            for game_id in game_ids:
                home_team_id = df[df["GAME_ID"] == game_id]["HOME_TEAM_ID"].iloc[0]
                home_team = teams.find_team_name_by_id(home_team_id)["nickname"]
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

    finished_game_ids = []
    while gameid_token:
        logger.info("----------------------====================----------------------")
        to_check = False
        for game_id in list(gameid_token.keys()):
            home_team = gameid_token[game_id]["homeTeam"]["team"]
            away_team = gameid_token[game_id]["awayTeam"]["team"]
            if game_id in finished_game_ids:
                continue
            try:
                box = boxscore.BoxScore(game_id, timeout=5)
                info = box.game.get_dict()  # equal to box.get_dict()["game"]
                assert (
                    info["awayTeam"]["teamName"] == away_team
                    and info["homeTeam"]["teamName"] == home_team
                ), "error, away team name not match"
            except Exception as e:
                logger.info(
                    f"query game {away_team} vs. {home_team} fail: {game_id} with {e}"
                )
                # don"t sleep here
                to_check = True
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
                if flip_rate < 0.005:
                    logger.info(info_str)
                    logger.info(
                        f"{game_id}: {away_team} vs. {home_team} flip rate: {flip_rate}"
                    )
                    tokens = [
                        gameid_token[game_id]["homeTeam"]["outcome_token_id"],
                        gameid_token[game_id]["awayTeam"]["outcome_token_id"],
                    ]
                    buy_in(tokens=tokens, price_threshold=0.8)
                    exit()
            if info["gameStatus"] == 3:
                logger.info(f"{game_id}: {away_team} vs. {home_team} finished")
                logger.info(f"score: {away_team_score} - {home_team_score}")
                try:
                    logger.info(f"buy in finished game: {game_id}")
                    buy_in(gameid_token[game_id])
                    exit()
                except Exception as e:
                    logger.info(f"buy in finished game fail: {e}")
                finished_game_ids.append(game_id)
            logger.info(info_str)
        if not to_check:
            logger.info("no game to check, sleep for 5 minutes")
            time.sleep(300)
