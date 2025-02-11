import os
import sys
import threading
import time
from json.decoder import JSONDecodeError
from pathlib import Path
from typing import Dict, Optional

import certifi
import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal
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


class GameSignals(QObject):
    status_updated = pyqtSignal(str, str)


class NBAGame:
    def __init__(
        self,
        game_id: str,
        home_team: str,
        home_token: str,
        away_team: str,
        away_token: str,
        game_date: str,
        price_limit: float,
        loss_sell_th: float,
        profit_sell_th: float,
        buy_balance: float,
        df: pd.DataFrame,
    ):
        self.game_id = game_id
        self.home_team = home_team
        self.home_token = home_token
        self.away_team = away_team
        self.away_token = away_token
        self.game_date = game_date
        self.price_limit = price_limit
        self.loss_sell_th = loss_sell_th
        self.profit_sell_th = profit_sell_th
        self.buy_balance = buy_balance
        self.df = df

        self.match_up = f"{away_team}_{home_team}"
        self.logger = setup_logger(
            self.match_up, f"logs/{game_date}/{self.match_up}.log"
        )
        self.signals = GameSignals()

        self._running = False
        self._lock = threading.Lock()
        self.real_tokens: Dict[str, Dict] = {}
        self.fake_tokens: Dict[str, Dict] = {}

        self.buy_thread: Optional[threading.Thread] = None
        self.price_monitor_thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self.buy_thread = threading.Thread(target=self._monitor_game, daemon=True)
        self.price_monitor_thread = threading.Thread(
            target=self._monitor_prices, daemon=True
        )
        self.buy_thread.start()
        self.price_monitor_thread.start()

    def stop(self):
        self._running = False
        self._cleanup_tokens()

    def _log_and_emit(self, message: str):
        self.logger.info(message)
        self.signals.status_updated.emit(self.match_up, message)

    def _cleanup_tokens(self):
        with self._lock:
            for token in [self.home_token, self.away_token]:
                if token in self.real_tokens:
                    del self.real_tokens[token]
                if token in self.fake_tokens:
                    del self.fake_tokens[token]

    def _monitor_game(self):
        bought_str = ""
        fake_bought_str = ""

        while self._running:
            game_info = self._get_game_info()
            if not game_info:
                continue

            status_text = game_info["gameStatusText"]
            if self._is_early_game(status_text):
                self._log_and_emit(f"{self.match_up} {status_text}, sleeping")
                time.sleep(60)
                continue

            if self._is_late_game(status_text):
                bought_str, fake_bought_str = self._process_late_game(
                    game_info, bought_str, fake_bought_str
                )

            if game_info["gameStatus"] == 3:
                self._handle_game_end()
                break

    def _get_game_info(self) -> Optional[Dict]:
        try:
            box = boxscore.BoxScore(self.game_id, timeout=3)
            info = box.game.get_dict()
            assert (
                info["awayTeam"]["teamName"] == self.away_team
                and info["homeTeam"]["teamName"] == self.home_team
            )
            return info
        except (ReadTimeout, JSONDecodeError):
            self._log_and_emit(f"Game {self.match_up} not started, sleeping")
            time.sleep(300)
        except Exception as e:
            self.logger.error(f"Error getting game info: {e}")
        return None

    def _process_late_game(
        self, game_info: Dict, bought_str: str, fake_bought_str: str
    ) -> tuple:
        home_score = game_info["homeTeam"]["score"]
        away_score = game_info["awayTeam"]["score"]
        status_text = game_info["gameStatusText"]

        try:
            time_played = get_time_played(status_text)
        except ValueError as e:
            self.logger.error(f"Error parsing time: {e}")
            return bought_str, fake_bought_str

        score_diff = away_score - home_score
        flip_rate = check_flip(time_played, score_diff, self.df, self.logger)
        leading_team, leading_token = self._get_leading_team_and_token(
            away_score, home_score
        )

        fake_bought_str = self._process_fake_buy(
            flip_rate,
            leading_team,
            leading_token,
            fake_bought_str,
            status_text,
            away_score,
            home_score,
        )

        bought_str = self._process_real_buy(
            flip_rate, leading_team, leading_token, bought_str, status_text
        )

        status_message = (
            f"{self.away_team} {away_score} - {self.home_team} {home_score} "
            f"Status: {status_text} Flip rate: {flip_rate:.4f} {bought_str}"
        )
        self._log_and_emit(status_message)
        return bought_str, fake_bought_str

    def _get_leading_team_and_token(self, away_score: int, home_score: int) -> tuple:
        if away_score > home_score:
            return self.away_team, self.away_token
        return self.home_team, self.home_token

    def _process_fake_buy(
        self,
        flip_rate: float,
        leading_team: str,
        leading_token: str,
        fake_bought_str: str,
        status_text: str,
        away_score: int,
        home_score: int,
    ) -> str:
        if flip_rate < 0.05 and not fake_bought_str:
            try:
                bought, price_pair, size = buy_in(
                    tokens=[leading_token],
                    price_threshold=1.0,
                    price_limit=0.0,
                    buy_balance=self.buy_balance,
                    logger=self.logger,
                )

                if not bought:
                    fake_bought_str = (
                        f"Fake bought {leading_team} {size}@{price_pair[0]} "
                        f"Flip: {flip_rate:.4f} {status_text} {away_score}-{home_score}"
                    )
                    with self._lock:
                        self.fake_tokens[leading_token] = {
                            "price": price_pair[0],
                            "size": size,
                            "team": leading_team,
                        }
                    self._log_and_emit(fake_bought_str)
            except Exception as e:
                self.logger.error(f"Fake buy failed: {e}")
        return fake_bought_str

    def _process_real_buy(
        self,
        flip_rate: float,
        leading_team: str,
        leading_token: str,
        bought_str: str,
        status_text: str,
    ) -> str:
        if flip_rate < 0.005 and not bought_str:
            try:
                bought, price_pair, size = buy_in(
                    tokens=[leading_token],
                    price_threshold=0.7,
                    price_limit=self.price_limit,
                    buy_balance=self.buy_balance,
                    logger=self.logger,
                )

                if bought:
                    bought_str = (
                        f"Bought {leading_team} {size}@{price_pair[0]} "
                        f"Flip: {flip_rate:.4f} {status_text}"
                    )
                    with self._lock:
                        self.real_tokens[leading_token] = {
                            "price": price_pair[0],
                            "size": size,
                            "team": leading_team,
                        }
                else:
                    bought_str = f"Failed to buy {leading_team}"
                self._log_and_emit(bought_str)
            except Exception as e:
                self.logger.error(f"Real buy failed: {e}")
                bought_str = ""
        return bought_str

    def _monitor_prices(self):
        while self._running:
            with self._lock:
                tokens_to_check = list(self.real_tokens.keys()) + list(
                    self.fake_tokens.keys()
                )

            if not tokens_to_check:
                time.sleep(10)
                continue

            try:
                book_params = [
                    {"token": token, "side": "BUY"} for token in tokens_to_check
                ]
                prices = client.get_prices(book_params)

                self._process_real_tokens(prices)
                self._process_fake_tokens(prices)

            except Exception as e:
                self.logger.error(f"Price monitoring error: {e}")

            time.sleep(10)

    def _process_real_tokens(self, prices: Dict):
        for token in list(self.real_tokens.keys()):
            if token not in prices:
                continue

            current_price = float(prices[token]["BUY"])
            token_info = self.real_tokens[token]
            price_diff = token_info["price"] - current_price

            if (
                price_diff > self.loss_sell_th
                or current_price - token_info["price"] > self.profit_sell_th
            ):
                self._sell_token(token, token_info, current_price)

    def _process_fake_tokens(self, prices: Dict):
        for token in list(self.fake_tokens.keys()):
            if token not in prices:
                continue

            current_price = float(prices[token]["BUY"])
            token_info = self.fake_tokens[token]
            if token_info["price"] - current_price > self.loss_sell_th:
                with self._lock:
                    if token in self.fake_tokens:
                        del self.fake_tokens[token]

    def _sell_token(self, token: str, token_info: Dict, current_price: float):
        try:
            sell_with_market_price(token, token_info["size"], self.logger)
            message = (
                f"Sold {token_info['team']} {token_info['size']} shares "
                f"at {current_price:.4f} (Bought: {token_info['price']:.4f})"
            )
            self._log_and_emit(message)
            with self._lock:
                del self.real_tokens[token]
        except Exception as e:
            self.logger.error(f"Failed to sell {token}: {e}")

    def _handle_game_end(self):
        self._log_and_emit(f"Game finished {self.match_up}")
        self._cleanup_tokens()
        self.stop()

    @staticmethod
    def _is_early_game(status_text: str) -> bool:
        return any(stage in status_text for stage in ["Half", "pre", "Q1", "Q2"])

    @staticmethod
    def _is_late_game(status_text: str) -> bool:
        return any(stage in status_text for stage in ["Q3", "Q4", "OT"])


class NBATrader:
    def __init__(
        self,
        game_date: str,
        price_limit: float = 0.998,
        loss_sell_th: float = 0.2,
        profit_sell_th: float = 0.008,
        buy_balance: float = 100.0,
    ):
        self.logger = setup_logger("main", f"logs/{game_date}/main.log")
        self.game_date = game_date
        self.price_limit = price_limit
        self.loss_sell_th = loss_sell_th
        self.profit_sell_th = profit_sell_th
        self.buy_balance = buy_balance

        self.games: Dict[str, NBAGame] = {}
        self.qt_window: Optional[ThreadDisplayWindow] = None
        self._load_data()

    def _load_data(self):
        csv_file = Path(__file__).parent / "assets/fromq3/fromq3_merged.csv"
        self.logger.info(f"Loading data from {csv_file}")
        self.df = pd.read_csv(csv_file)

    def setup_games(self):
        team_token = get_team_token(self.game_date, "nba")
        board = ScoreboardV2(game_date=self.game_date)

        game_data = None
        for data_set in board.data_sets:
            df = data_set.get_data_frame()
            if "GAME_ID" in df.columns and "HOME_TEAM_ID" in df.columns:
                game_data = df
                break

        if game_data is None:
            raise ValueError("No game data found")

        window_names = []
        for _, row in game_data.iterrows():
            game_id = row["GAME_ID"]
            home_team = teams.find_team_name_by_id(row["HOME_TEAM_ID"])["nickname"]
            away_team = teams.find_team_name_by_id(row["VISITOR_TEAM_ID"])["nickname"]

            if home_team not in team_token or away_team not in team_token:
                self.logger.warning(f"Missing token for {home_team} or {away_team}")
                continue

            game = NBAGame(
                game_id=game_id,
                home_team=home_team,
                home_token=team_token[home_team],
                away_team=away_team,
                away_token=team_token[away_team],
                game_date=self.game_date,
                price_limit=self.price_limit,
                loss_sell_th=self.loss_sell_th,
                profit_sell_th=self.profit_sell_th,
                buy_balance=self.buy_balance,
                df=self.df,
            )
            self.games[game_id] = game
            window_names.append(f"{away_team}_{home_team}")

        self.qt_window = ThreadDisplayWindow(window_names)
        self._connect_signals()

    def _connect_signals(self):
        for game in self.games.values():
            game.signals.status_updated.connect(self.qt_window.print)

    def start_trading(self):
        app = QApplication(sys.argv)
        self.setup_games()
        self.qt_window.show()

        for game in self.games.values():
            game.start()

        app.exec()
        self._shutdown()

    def _shutdown(self):
        for game in self.games.values():
            game.stop()
        self.logger.info("All games stopped")


if __name__ == "__main__":
    import signal

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    trader = NBATrader(
        game_date="2025-02-09",
        price_limit=0.998,
        loss_sell_th=0.2,
        profit_sell_th=0.008,
        buy_balance=100.0,
    )
    trader.start_trading()
