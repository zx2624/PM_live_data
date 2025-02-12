import json
import logging
import os
import sys
import threading
import time
from json.decoder import JSONDecodeError
from multiprocessing import Manager
from pathlib import Path
from typing import Dict, List

import certifi
import pandas as pd
from py_clob_client.clob_types import BookParams
from py_clob_client.order_builder.constants import BUY, SELL
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

os.environ["SSL_CERT_FILE"] = certifi.where()
game_date = "2025-02-10"
price_limit = 0.998
loss_sell_th = 0.2
profit_sell_th = 0.008
buy_balance = 106.0


class NBATrader:
    def __init__(
        self,
        game_date: str,
        price_limit: float = 0.998,
        loss_sell_th: float = 0.2,
        profit_sell_th: float = 0.008,
        buy_balance: float = 0.0,
    ):
        self.logger = setup_logger("main", f"logs/{game_date}/main.log")
        self.game_date = game_date
        self.price_limit = price_limit
        self.loss_sell_th = loss_sell_th
        self.profit_sell_th = profit_sell_th
        self.buy_balance = buy_balance

        self.manager = Manager()
        self.token_infos = self.manager.dict()
        self.fake_token_infos = self.manager.dict()
        self.gameid_token: Dict[str, Dict] = {}
        # load csv
        csv_file = (
            Path(os.path.abspath(__file__)).parent / "assets/fromq3/fromq3_merged.csv"
        )
        self.logger.info(f"loading csv file from {csv_file}")
        self.df = pd.read_csv(csv_file)
        self.qt_window = None
        self.threads: List[threading.Thread] = []

    def price_monitor(self):
        side = BUY
        logfile = f"logs/{self.game_date}/price_monitor.log"
        logger = setup_logger("price_monitor", logfile)

        while True:
            if len(self.token_infos) == 0 and len(self.fake_token_infos) == 0:
                logger.info("no token to sell, sleep for 60 seconds")
                time.sleep(60)
                continue

            bookparams = [
                BookParams(token, side)
                for token in list(self.token_infos.keys())
                + list(self.fake_token_infos.keys())
            ]

            try:
                prices = client.get_prices(bookparams)
            except Exception as e:
                logger.error(f"error when get prices: {e}")
                continue

            try:
                self._process_real_tokens(prices, side, logger)
                self._process_fake_tokens(prices, side, logger)
            except Exception as e:
                logger.error(f"error when process tokens: {e}")

    def _process_real_tokens(self, prices, side, logger: logging.Logger):
        for token in list(self.token_infos.keys()):
            shares = round(self.token_infos[token]["size"], 2)
            ori_price = self.token_infos[token]["price"]
            team = self.token_infos[token]["team"]

            if token not in prices:
                logger.warning(f"token {token} not in prices")
                continue

            price = float(prices[token][side])
            logger.info(
                f"{team} {token} shares: {shares}, ori_price: {ori_price}, current price: {price}"  # noqa
            )

            if ori_price - price > self.loss_sell_th:
                logger.warning(
                    f"price too low, sell {team} {token} at {price} for {shares} shares"
                )
                sell_with_market_price(token=token, size=shares, logger=logger)
                if token in self.token_infos:
                    self.token_infos.pop(token)
            elif price - ori_price > self.profit_sell_th:
                logger.info(
                    f"enough profit, sell {team} {token} at {price} for {shares} shares"
                )
                sell_with_market_price(token=token, size=shares, logger=logger)
                if token in self.token_infos:
                    self.token_infos.pop(token)

    def _process_fake_tokens(self, prices, side, logger: logging.Logger):
        for token in list(self.fake_token_infos.keys()):
            ori_price = self.fake_token_infos[token]["price"]
            team = self.fake_token_infos[token]["team"]

            if token not in prices:
                logger.warning(f"token {token} not in prices")
                continue

            price = float(prices[token][side])
            logger.info(
                f"{team} {token} fake ori_price: {ori_price}, current price: {price}"
            )

            if ori_price - price > self.loss_sell_th:
                logger.warning(f"fake price too low, sell {team} {token} at {price}")
                if token in self.fake_token_infos:
                    self.fake_token_infos.pop(token)
            if price - ori_price > 0.05:
                logger.info(f"fake enough profit, sell {team} {token} at {price}")
                if token in self.fake_token_infos:
                    self.fake_token_infos.pop(token)

    def buy_one_game(self, game_id: str):
        home_team = self.gameid_token[game_id]["homeTeam"]["team"]
        away_team = self.gameid_token[game_id]["awayTeam"]["team"]
        home_token = self.gameid_token[game_id]["homeTeam"]["outcome_token_id"]
        away_token = self.gameid_token[game_id]["awayTeam"]["outcome_token_id"]
        match_up = f"{away_team}_{home_team}"

        logfile = f"logs/{self.game_date}/{match_up}.log"
        logger = setup_logger(match_up, logfile)
        # TODO: deprecate this, not elegant
        bought_str = ""
        fake_bought_str = ""

        while True:
            game_info = self._get_game_info(game_id, away_team, home_team, logger)
            if not game_info:
                continue

            status_text = game_info["gameStatusText"]
            if self._is_early_game(status_text):
                logger.info(f"{away_team} vs. {home_team} {status_text}, sleeping")
                if self.qt_window:
                    self.qt_window.print(
                        match_up, f"{away_team} vs. {home_team} {status_text}, sleeping"
                    )
                time.sleep(60)
                continue

            if self._is_late_game(status_text):
                bought_str, fake_bought_str = self._process_late_game(
                    game_info,
                    away_team,
                    home_team,
                    away_token,
                    home_token,
                    bought_str,
                    fake_bought_str,
                    match_up,
                    logger,
                )

            if game_info["gameStatus"] == 3:
                self._handle_game_end(
                    game_id, away_team, home_team, away_token, home_token, logger
                )
                break

    def _get_game_info(self, game_id, away_team, home_team, logger):
        try:
            box = boxscore.BoxScore(game_id, timeout=5)
            info = box.game.get_dict()
            assert (
                info["awayTeam"]["teamName"] == away_team
                and info["homeTeam"]["teamName"] == home_team
            ), "error, away team name not match"
            return info
        except ReadTimeout as e:
            logger.info(f"query {away_team} VS {home_team} timeout {e}")
        except JSONDecodeError:
            logger.info(
                f"game {away_team} VS {home_team} not started, sleep for 5 minutes"
            )
            if self.qt_window:
                self.qt_window.print(
                    f"{away_team}_{home_team}",
                    f"game {away_team} VS {home_team} not started, sleep for 5 minutes",
                )
            time.sleep(300)
        except Exception as e:
            logger.info(f"{away_team} VS {home_team}, some error {e}")
        return None

    def _is_early_game(self, status_text: str) -> bool:
        early_stages = ["Half", "pre", "Q1", "Q2"]
        return any(stage in status_text for stage in early_stages)

    def _is_late_game(self, status_text: str) -> bool:
        late_stages = ["Q3", "Q4", "OT"]
        return any(stage in status_text for stage in late_stages)

    def _process_late_game(
        self,
        game_info,
        away_team,
        home_team,
        away_token,
        home_token,
        bought_str,
        fake_bought_str,
        match_up,
        logger,
    ):
        home_score = game_info["homeTeam"]["score"]
        away_score = game_info["awayTeam"]["score"]
        status_text = game_info["gameStatusText"]

        try:
            time_played = get_time_played(status_text)
        except Exception as e:
            logger.info(f"error: {e} with {status_text}")
            return bought_str, fake_bought_str

        flip_rate = check_flip(
            time_played, away_score - home_score, df=self.df, logger=logger
        )
        leading_team = away_team if away_score > home_score else home_team
        leading_token = away_token if away_score > home_score else home_token

        fake_bought_str = self._try_fake_buy(
            flip_rate,
            leading_team,
            leading_token,
            fake_bought_str,
            status_text,
            away_score,
            home_score,
            logger,
        )

        bought_str = self._try_real_buy(
            flip_rate, leading_team, leading_token, bought_str, status_text, logger
        )

        info_str = (
            f"{away_team} {away_score} - {home_team} {home_score} "
            f"status: {status_text} flip rate: {flip_rate} {bought_str}"
        )
        if self.qt_window:
            self.qt_window.print(match_up, info_str)
        logger.info(info_str)
        return bought_str, fake_bought_str

    def setup_games(self):
        team_token = get_team_token(self.game_date, "nba")
        board = ScoreboardV2(game_date=self.game_date)

        for data_set in board.data_sets:
            df = data_set.get_data_frame()
            if "GAME_ID" in df.columns and "HOME_TEAM_ID" in df.columns:
                self._process_game_data(df, team_token)
                break

        self.logger.info(self.gameid_token)
        self._save_game_data()
        self._setup_qt_window()

    def _handle_game_end(
        self,
        game_id: str,
        away_team: str,
        home_team: str,
        away_token: str,
        home_token: str,
        logger,
    ):
        """
        处理比赛结束时的清理工作
        """
        logger.info(f"{game_id}: {away_team} vs. {home_team} finished")
        if self.qt_window:
            self.qt_window.print(
                f"{away_team}_{home_team}", f"{away_team} vs. {home_team} finished"
            )
        # 等待一段时间，以防还有未完成的卖出操作
        time.sleep(10)

        # 清理可能存在的token信息
        for token in [away_token, home_token]:
            if token in self.token_infos:
                self.token_infos.pop(token)
            if token in self.fake_token_infos:
                self.fake_token_infos.pop(token)

        logger.info(f"{away_team} vs. {home_team} token poped")

    def _try_fake_buy(
        self,
        flip_rate: float,
        leading_team: str,
        leading_token: str,
        fake_bought_str: str,
        status_text: str,
        away_score: int,
        home_score: int,
        logger,
    ):
        """
        尝试进行模拟购买操作
        """
        if flip_rate < 0.05 and fake_bought_str == "":
            try:
                price = float(client.get_price(leading_token, SELL)["price"])
                order_book = client.get_order_book(leading_token)
                logger.info(f"order book: {order_book}")
                fake_bought_str = " ".join(
                    [
                        f"fake bought {leading_team}",
                        f"at {price} with flip_rate {flip_rate}",
                        f"{status_text}",
                        f"{away_score} - {home_score}",
                    ]
                )
                logger.info(fake_bought_str)
                # 记录模拟购买信息
                self.fake_token_infos[leading_token] = self.manager.dict()
                self.fake_token_infos[leading_token]["price"] = price
                self.fake_token_infos[leading_token]["size"] = 0
                self.fake_token_infos[leading_token]["team"] = leading_team
            except Exception:
                logger.info("error when get order book or price")
        return fake_bought_str

    def _try_real_buy(
        self,
        flip_rate: float,
        leading_team: str,
        leading_token: str,
        bought_str: str,
        status_text: str,
        logger,
    ):
        """
        尝试进行实际购买操作
        """
        if flip_rate < 0.005 and bought_str == "":
            try:
                bought, price_pair, size = buy_in(
                    tokens=[leading_token],
                    price_threshold=0.7,
                    price_limit=self.price_limit,
                    buy_balance=self.buy_balance,
                    logger=logger,
                )

                # 构建购买状态字符串
                bought_str = " ".join(
                    [
                        f"bought {leading_team} for {size} shares",
                        f"at {price_pair} with flip_rate {flip_rate}",
                        f"{status_text}",
                    ]
                )

                if bought:
                    # 记录实际购买信息
                    self.token_infos[leading_token] = self.manager.dict()
                    self.token_infos[leading_token]["size"] = size
                    self.token_infos[leading_token]["price"] = price_pair[0]
                    self.token_infos[leading_token]["team"] = leading_team
                else:
                    bought_str = f"not {bought_str}"

                logger.info(bought_str)

            except Exception as e:
                logger.info(f"buying {leading_team} fail: {e}")
        return bought_str

    def _process_game_data(self, df, team_token):
        df = df[["GAME_ID", "HOME_TEAM_ID", "VISITOR_TEAM_ID"]]
        game_ids = df["GAME_ID"].values

        for game_id in game_ids:
            home_team_id = df[df["GAME_ID"] == game_id]["HOME_TEAM_ID"].iloc[0]
            home_team = teams.find_team_name_by_id(home_team_id)["nickname"]

            if home_team not in team_token:
                self.logger.info(f"{home_team} not in outcome_token_id")
                continue

            visitor_team_id = df[df["GAME_ID"] == game_id]["VISITOR_TEAM_ID"].iloc[0]
            visitor_team = teams.find_team_name_by_id(visitor_team_id)["nickname"]

            self.gameid_token[game_id] = {
                "homeTeam": {
                    "team": home_team,
                    "outcome_token_id": team_token[home_team],
                },
                "awayTeam": {
                    "team": visitor_team,
                    "outcome_token_id": team_token[visitor_team],
                },
            }

    def _save_game_data(self):
        with open(f"assets/gameid_infos/gameid_token_{self.game_date}.json", "w") as f:
            json.dump(self.gameid_token, f, indent=4)
        self.logger.info(
            f"price_limit {self.price_limit}, buy_balance {self.buy_balance}"
        )

    def _setup_qt_window(self):
        window_names = [
            f"{self.gameid_token[game_id]['awayTeam']['team']}_{self.gameid_token[game_id]['homeTeam']['team']}"  # noqa
            for game_id in self.gameid_token
        ]
        self.qt_window = ThreadDisplayWindow(window_names)
        self.qt_window.show()

    def start_trading(self):
        """Start the trading system"""
        # Start Qt application
        app = QApplication(sys.argv)

        self.setup_games()

        # Start game monitoring threads
        for game_id in self.gameid_token:
            thread = threading.Thread(target=self.buy_one_game, args=(game_id,))
            self.threads.append(thread)
            thread.start()

        # Start selling monitoring thread
        sell_thread = threading.Thread(target=self.price_monitor)
        sell_thread.start()
        self.threads.append(sell_thread)
        app.exec()

        # Wait for all threads to complete
        for thread in self.threads:
            thread.join()

        self.logger.info("All games finished!")


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    trader = NBATrader(
        game_date=game_date,
        price_limit=price_limit,
        loss_sell_th=loss_sell_th,
        profit_sell_th=profit_sell_th,
        buy_balance=buy_balance,
    )
    trader.start_trading()
