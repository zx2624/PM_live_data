import json
import logging
import os
from collections import defaultdict

import numpy as np
from matplotlib import pyplot as plt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # check price tumble
    # after price hit certain price, check the rmain prices
    # plot with matplotlib bin 0.01
    check_price = 0.99
    prices_folder = "history_prices/prices"
    json_files = os.listdir(prices_folder)
    bin_res = 0.2
    bins = {}
    valid_cnt = 0
    failed_cnt = 0
    for json_file in json_files:
        logger.info(f"Processing {json_file}")
        market_id = json_file.split("_")[0]
        token_id = json_file.split("_")[1]
        with open(f"{prices_folder}/{json_file}", "r") as f:
            prices = json.load(f)
        if len(prices) == 0:
            continue
        # reverse prices
        prices = prices[::-1]
        if not (prices[-1] >= 0.99 or prices[-1] <= 0.01):
            continue
        # filter prices cnt < 100
        if len(prices) < 100:
            continue
        # only use half of the prices
        # prices = prices[len(prices)//2:]
        prices = np.array(prices)
        # 1. get the first price that hit check_price
        idx = np.where(prices >= check_price)[0]
        if len(idx) == 0:
            continue
        valid_cnt += 1
        if prices[-1] <= 0.01:
            failed_cnt += 1
        idx = idx[0]
        # 2. get the rest prices
        rest_prices = prices[idx:]
        # 3. get lowest price
        lowest_price = np.min(rest_prices)
        # 4. get the bin
        bin_idx = int((lowest_price - check_price) / bin_res)
        if bin_idx not in bins:
            bins[bin_idx] = 0
        bins[bin_idx] += 1
    logger.info(f"valid_cnt: {valid_cnt} / {len(json_files)}")
    logger.info(f"failed_cnt: {failed_cnt}")
    logger.info(f"bins: {bins}")
    # plot
    x = list(bins.keys())
    y = list(bins.values())
    plt.bar(x, y)
    plt.savefig("price_tumble.png")
