import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    ori_prices = "history_prices/ori"
    prices_folder = "history_prices/prices"
    os.makedirs(prices_folder, exist_ok=True)
    json_files = os.listdir(ori_prices)
    for json_file in json_files:
        logger.info(f"Processing {json_file}")
        market_id = json_file.split(".")[0]
        with open(f"{ori_prices}/{json_file}", "r") as f:
            data = json.load(f)
        for token_id, order_fill_events in data.items():
            if len(order_fill_events) == 0:
                continue
            prices = []
            for order_fill_event in order_fill_events:
                price = float(order_fill_event["makerAmountFilled"]) / float(
                    order_fill_event["takerAmountFilled"]
                )
                prices.append(price)
            with open(f"{prices_folder}/{market_id}_{token_id}", "w") as f:
                json.dump(prices, f, indent=4)
