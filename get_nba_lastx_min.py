from nba_api.stats.endpoints import leaguegamefinder, playbyplayv2
import pandas as pd
from tqdm import tqdm  # 用于显示进度条
from concurrent.futures import ThreadPoolExecutor
import logging
logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)

def quater_pct_to_sec(quater, pct): 
    """
    Convert to seconds from the start of the game
    """
    quater = int(quater)
    # pctimestring like 05:14, meaning 5 minutes and 14 seconds left in the quater
    pct = pct.split(":")
    pct_sec = int(pct[0]) * 60 + int(pct[1]) if len(pct) == 2 else 0
    # 1~4 quater
    if quater < 5:
        return quater * 12 * 60 - pct_sec
    # overtime
    else:
        return 4 * 12 * 60 + (quater - 4) * 5 * 60 - pct_sec

def process_one(game_id):
    try:
        # filter last quater plays, including overtime
        play_by_play = playbyplayv2.PlayByPlayV2(game_id=game_id, timeout=5).get_data_frames()[0]
        play_by_play = play_by_play[play_by_play['SCOREMARGIN'].notna()]
        last_quater = int(play_by_play["PERIOD"].max())
        # convert PCTIMESTRING to seconds from the start of the game
        play_by_play["TIMEPLAYED"] = play_by_play.apply(
            lambda x: quater_pct_to_sec(x["PERIOD"], x["PCTIMESTRING"]), axis=1
        )
        # get socre margin of every second in last 120 seconds
        result = {
            "GAME_ID": game_id
        }
        # get Q3 ~ end of the game by seconds
        # assuming 2 OTs at most
        for i in range(2 * 12 * 60, 2880 + (last_quater - 4) * 5 * 60 + 1):
            result[i] = play_by_play[play_by_play['TIMEPLAYED'] <= i].iloc[-1]["SCOREMARGIN"]
            if result[i] == "TIE":
                result[i] = 0
        return result, game_id
    except Exception as e:
        logger.info(f"Error processing game {game_id}: {e}")
        return False, game_id
    
try:
    with open("failed_games.txt", "r") as f:
        his_failed_games = f.read().split("\n")
except:
    his_failed_games = []

# 获取2020赛季至今的比赛列表
seasons = list(range(15, 24))
# 初始化存储结果
new_failed_games = []
import time
time_stamp = time.time()
for season in seasons:
    season = f"20{season:02d}-{season+1:02d}"
    results = []
    logger.info(f"Processing season {season}")
    while True:
        try:
            gamefinder = leaguegamefinder.LeagueGameFinder(season_nullable=season, timeout=5)  # 替换为目标赛季
            games = gamefinder.get_data_frames()[0]
            logger.info(f"season {season} has {len(games)} games")
            break
        except Exception as e:
            logger.info(f"Error getting games: {e}")
    games = gamefinder.get_data_frames()[0]
    # logger.info(len(games))
    # logger.info(games)
    # # 提取需要的字段
    # games = games[['GAME_ID', 'GAME_DATE', 'MATCHUP', 'WL', 'PTS', 'PLUS_MINUS']]
    game_ids = list(set(games["GAME_ID"].tolist()))
    game_ids = list(set(game_ids).intersection(set(his_failed_games)))
    # process failed games
    logger.info(f"season {season} has {len(game_ids)} games un processed")
    # use ThreadPoolExecutor and tqdm to show progress bar
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(tqdm(executor.map(process_one, game_ids), total=len(game_ids)))
    filtered_results = []
    for result in results:
        if result[0]:
            filtered_results.append(result[0])
        else:
            new_failed_games.append(result[1])
    results = filtered_results
    results_df = pd.DataFrame(results)

    # # 保存或输出
    # # logger.info(results_df.head())
    logger.info(f"season {season} has {len(results_df)} games")
    file_name = f"nba_from_q3_{season}_{time_stamp}.csv"
    logger.info(f"saving to {file_name}")
    results_df.to_csv(f"{file_name}", index=False)
logger.info(f"new failed games: {len(new_failed_games)}")
with open("failed_games.txt", "w") as f:
    f.write("\n".join(new_failed_games))