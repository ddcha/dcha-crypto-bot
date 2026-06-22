from exchange_bybit import BybitExchange
from settings_store import load_live_settings, get_api_settings, get_mode
import json
s = load_live_settings()
api = get_api_settings(s)
mode = get_mode(s)
key = api['demo_api_key'] if mode == 'demo' else api['live_api_key']
sec = api['demo_api_secret'] if mode == 'demo' else api['live_api_secret']
ex = BybitExchange(api_key=key, api_secret=sec, use_demo=(mode == 'demo'))
for sym in ['BNBUSDT', 'ADAUSDT']:
    info = ex.session.get_instruments_info(category='linear', symbol=sym)
    print(sym, json.dumps(info['result']['list'][0]['lotSizeFilter'], indent=2))
