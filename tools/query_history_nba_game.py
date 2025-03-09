import json
import os

import certifi

from agents.polymarket.gamma import GammaMarketClient as Gamma

os.environ["SSL_CERT_FILE"] = certifi.where()

tag_slug = "nba"
gamma = Gamma()
# event
querystring_params = {
    "limit": 100000,
    "offset": 0,
    # "active": True,
    # "closed": True,
    "related_tags": True,
    "tag_slug": tag_slug,
}
# markets
querystring_params = {
    "limit": 1000,
    "offset": 1500,
    # "active": True,
    # "closed": True,
    "related_tags": True,
    "tag_id": 745,
}
# events = gamma.get_events(querystring_params=querystring_params)

# for i in range(0, 2500, 500):
#     querystring_params["offset"] = i
#     markets = gamma.get_markets(querystring_params=querystring_params)
#     all_markets.extend(markets)
#     print(len(markets))
# with open("query_history_nba_game.json", "w") as f:
#     json.dump(all_markets, f, indent=4)

with open("query_history_nba_game.json", "r") as f:
    all_markets = json.load(f)
filtered_markets = []
for market in all_markets:
    desc = market["description"]
    # set all desc to lowercase
    desc = desc.lower()
    if "nba game" in desc or "nba playoff" in desc:
        filtered_markets.append(market)
print(len(filtered_markets))
with open("query_history_nba_game_filtered.json", "w") as f:
    json.dump(filtered_markets, f, indent=4)
