import requests

url = "https://fapi.binance.com/fapi/v1/ticker/24hr"

data = requests.get(url).json()

for coin in data[:10]:
    print(coin["symbol"], coin["priceChangePercent"])