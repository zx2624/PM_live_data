from tools.utils import buy_in, get_team_token
import time

if __name__ == "__main__":

    price_threshold = 1
    # "[\"95734957567728541589925323298191125530139206154995084405557767668645819543553\", \"100426019216277606044639877310517734071097793713345871109253390440993379229340\"]"
    tokens =[
        "95734957567728541589925323298191125530139206154995084405557767668645819543553", "100426019216277606044639877310517734071097793713345871109253390440993379229340"
    ]
    sleep_time = 60
    while True:
        print(f"======================{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}======================")
        try:
            price = buy_in(tokens=tokens, price_threshold=price_threshold)
            if price > 0.9:
                sleep_time = 0.005
            else:
                sleep_time = 1
        except Exception as e:
            print(f"error: {e}")
        time.sleep(sleep_time)
