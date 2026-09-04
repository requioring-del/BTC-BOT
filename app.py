def btc_monitor_loop():
  global latest_btc_price
  print("BTC Monitoring loop started...", flush=True)
  url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"

  while True:
    try:
      response = requests.get(url, timeout=10)
      data = response.json()

      if "data" in data and "amount" in data["data"]:
        current_price = float(data["data"]["amount"])
        latest_btc_price = f"${current_price:,.2f}"
        print(f"Current BTC Price: {latest_btc_price}", flush=True)

        if current_price >= TARGET_PRICE:
          send_telegram_alert(
              f"🚨 BTC Alert! Price reached ${current_price:,.2f}"
          )
          time.sleep(300)
      else:
        print(f"Unexpected API response: {data}", flush=True)

    except Exception as e:
      print(f"Error fetching BTC price: {e}", flush=True)

    time.sleep(15)