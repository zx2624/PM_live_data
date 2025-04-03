import json
import logging
import os
from multiprocessing import Pool

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
target_folder = "history_prices/ori"
os.makedirs(target_folder, exist_ok=True)
processed_markets = []
if os.path.exists(target_folder):
    for file in os.listdir(target_folder):
        processed_markets.append(file.split(".")[0])

# 设置 GraphQL 端点 URL
graph_url = "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/prod/gn"


def query_one_market(market: dict) -> list:
    market_id = market["id"]
    logger.info(f"Querying market {market_id}")
    clobTokenIds = json.loads(market["clobTokenIds"])
    token_id_order_fill_events = {}
    for token_id in clobTokenIds:
        query_cnt = 0
        order_fill_events = []
        try:
            while True:
                query_template = """
                {{
                    orderFilledEvents(
                        where: {{ takerAssetId: "{taker_asset_id}" }}
                        orderBy: timestamp
                        orderDirection: desc
                        first:500
                        skip:{skip}
                    ) {{
                        id
                        transactionHash
                        timestamp
                        makerAmountFilled
                        takerAmountFilled
                        fee
                    }}
                }}
                """
                formatted_query = query_template.format(
                    taker_asset_id=token_id, skip=query_cnt * 500
                )

                # 发送请求
                response = requests.post(graph_url, json={"query": formatted_query})
                # 获取并打印响应数据
                data = response.json()
                order_fill_events.extend(data["data"]["orderFilledEvents"])
                if len(data["data"]["orderFilledEvents"]) < 500:
                    break
                query_cnt += 1
        except Exception as e:
            logger.error(f"Error querying market {market_id}: {e}")
            return False
        token_id_order_fill_events[token_id] = order_fill_events
    with open(f"{target_folder}/{market_id}.json", "w") as f:
        json.dump(token_id_order_fill_events, f, indent=4)
    return True


if __name__ == "__main__":
    with open("query_history_nba_game_filtered.json", "r") as f:
        all_markets = json.load(f)

    filtered_markets = [
        market for market in all_markets if market["id"] not in processed_markets
    ]
    logger.info(f"Total {len(filtered_markets)} markets to query")
    with Pool(8) as p:
        res = p.map(query_one_market, filtered_markets)
    success_cnt = sum(res)
    logger.info(f"Successfully queried {success_cnt} markets")
