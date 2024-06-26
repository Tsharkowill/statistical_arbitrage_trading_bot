import json
import pandas as pd
import os
import time
from constants import ORDER_SIZE
import bitget.v1.mix.order_api as maxOrderApi
from bitget.bitget_api import BitgetApi
from bitget.exceptions import BitgetAPIException
from decouple import config

apiKey = config('apiKey')
secretKey = config('secretKey')
passphrase = config('passphrase')

baseApi = BitgetApi(apiKey, secretKey, passphrase)




def filter_and_save_tradable_pairs(optimal_parameters_file, test_results_file, output_file):
  # Load the JSON data from files
  with open(optimal_parameters_file, 'r') as f:
      optimal_parameters = json.load(f)
  
  with open(test_results_file, 'r') as f:
      test_results = json.load(f)
  
  # Initialize a dictionary to hold tradable pairs with optimal parameters
  tradable_pairs = {}

  # Iterate through the test results and filter based on Sharpe ratio
  for market, results in test_results.items():
      if results['SharpeRatio'] >= 1:
          # Check if market exists in optimal parameters
          if market in optimal_parameters:
              # Add the market and its parameters to tradable pairs
              tradable_pairs[market] = optimal_parameters[market]

  # Save the tradable pairs with their parameters to a new JSON file
  with open(output_file, 'w') as f:
      json.dump(tradable_pairs, f, indent=4)
  
  print(f"Tradable pairs saved to {output_file}")



def calculate_spread(price_data_file, cointegrated_pairs_file):
  if not os.path.exists(cointegrated_pairs_file):
      return      
  price_data = pd.read_csv(price_data_file)
  cointegrated_pairs = pd.read_csv(cointegrated_pairs_file)
  spreads_df = pd.DataFrame(index=price_data.index)
  spreads_df['time'] = price_data['time']
  for _, row in cointegrated_pairs.iterrows():
      base_asset = row['Base']
      quote_asset = row['Quote']
      hedge_ratio = row['HedgeRatio']
      spread_name = f'{base_asset}_{quote_asset}'
      spreads_df[spread_name] = price_data[base_asset] - (hedge_ratio * price_data[quote_asset])
          

  return spreads_df



def calculate_zscore(market, spreads_df, WINDOW):
  spread_series = spreads_df[market]
  mean = spread_series.rolling(window=WINDOW).mean()
  std = spread_series.rolling(window=WINDOW).std()
  spreads_df[f'z_score_{market}'] = (spread_series - mean) / std



def manage_trades(spreads_file, cointegrated_pairs_file, price_data_file):
    spreads_df = pd.read_csv(spreads_file)

    price_data = pd.read_csv(price_data_file)

    cointegrated_pairs = pd.read_csv(cointegrated_pairs_file)


    # Load open positions from JSON if it exists, else initialize an empty dictionary
    try:
        with open('open_positions.json', 'r') as json_file:
            open_positions = json.load(json_file)
        print(f'Open positions loaded: {open_positions}')
    except FileNotFoundError:
        open_positions = {}
        print('No open positions found, starting fresh')

    keys_to_remove = []

    for _, row in cointegrated_pairs.iterrows():
        market = f"{row['Base']}_{row['Quote']}"
        print(f"\nProcessing market: {market}")
        base_asset, quote_asset = market.split('_')
        WINDOW = 200
        ENTRY_Z = 3.0
        EXIT_Z = 1.0

        print("Calculating Z-scores...")
        calculate_zscore(market, spreads_df, WINDOW)

        z_score_column = f'z_score_{market}'
        
        latest_row = spreads_df.iloc[-1]
        current_z_score = latest_row[z_score_column]
        print(current_z_score)
        current_spread = latest_row[market]
        key_to_remove = None
  
        # Determine if any trade logic needs to be processed
        if market not in open_positions:
            if current_z_score > ENTRY_Z:  # Enter positions with base asset shorted and quote asset longed
                enter_trade_pair(base_asset, quote_asset, "short/long", price_data, cointegrated_pairs, open_positions, current_spread)
                # open_positions[market] = {"position_type": "short/long", "entry_spread": current_spread}
            elif current_z_score < -ENTRY_Z:  # Enter positions with base asset longed and quote asset shorted
                enter_trade_pair(base_asset, quote_asset, "long/short", price_data, cointegrated_pairs, open_positions, current_spread)
                # open_positions[market] = {"position_type": "long/short", "entry_spread": current_spread}
        elif market in open_positions:
            position_type = open_positions[market]['position_type']

            if position_type == "short/long" and current_z_score <= -EXIT_Z:
                print(f"Exiting short/long position for market: {market}")
                key_to_remove = exit_trade_pair(base_asset, quote_asset, position_type, open_positions)

            elif position_type == "long/short" and current_z_score >= EXIT_Z:
                print(f"Exiting long/short position for market: {market}")
                key_to_remove = exit_trade_pair(base_asset, quote_asset, position_type, open_positions)
        
            if key_to_remove is not None:
                keys_to_remove.append(key_to_remove)    

    for key in keys_to_remove:
        if key in open_positions:
            del open_positions[key]

        # Additional logic for updating portfolio values or tracking trades can be added here

    # Consider persisting open_positions to a file if needed for longer-term tracking beyond script execution
    with open('open_positions.json', 'w') as json_file:
        json.dump(open_positions, json_file, indent=4)

          

def enter_trade_pair(base_asset, quote_asset, position_type, price_data, cointegrated_pairs, open_positions, current_spread):
  
    # Use latest price to determine position size
    base_asset_latest_price = price_data[base_asset].iloc[-1]

    # Calculate position size for base asset
    base_asset_position_size = ORDER_SIZE / base_asset_latest_price

    # Get hedge ratio for base/quote pair
    hedge_ratio_row = cointegrated_pairs[(cointegrated_pairs['Base'] == base_asset) & (cointegrated_pairs['Quote'] == quote_asset)]
    if not hedge_ratio_row.empty:
        hedge_ratio = hedge_ratio_row['HedgeRatio'].values[0]
    else:
        print(f"Hedge ratio not found for {base_asset} and {quote_asset}, skipping trade.")
        return


    # Calculate position size for quote asset
    quote_asset_position_size = base_asset_position_size * hedge_ratio
    
    if position_type == "short/long":
        # Short the base asset
        print(f"Shorting {base_asset}")
        params_base = {
            "symbol": f"{base_asset}_UMCBL",
            "marginCoin": "USDT",
            "side": "open_short",
            "orderType": "market",
            "size": base_asset_position_size,
            "timInForceValue": "normal"
        }
        # Long the quote asset
        print(f"Longing {quote_asset}")
        params_quote = {
            "symbol": f"{quote_asset}_UMCBL",
            "marginCoin": "USDT",
            "side": "open_long",
            "orderType": "market",
            "size": quote_asset_position_size,
            "timInForceValue": "normal"
        }
    elif position_type == "long/short":
        # Long the base asset
        print(f"Longing {base_asset}")
        params_base = {
            "symbol": f"{base_asset}_UMCBL",
            "marginCoin": "USDT",
            "side": "open_long",
            "orderType": "market",
            "size": base_asset_position_size,
            "timInForceValue": "normal"
        }
        # Short the quote asset
        print(f"Shorting {quote_asset}")
        params_quote = {
            "symbol": f"{quote_asset}_UMCBL",
            "marginCoin": "USDT",
            "side": "open_short",
            "orderType": "market",
            "size": quote_asset_position_size,
            "timInForceValue": "normal"
        }

    
    # Execute the trades
    order_api = maxOrderApi.OrderApi(apiKey, secretKey, passphrase)
    try:
        response_base = order_api.placeOrder(params_base)
        print(response_base)
    except BitgetAPIException as e:
        print("error:" + e.message)
    try:
        response_quote = order_api.placeOrder(params_quote)
        print(response_quote)
    except BitgetAPIException as e:
        print("error:" + e.message)

    # Save opened positions
    open_positions[f"{base_asset}_{quote_asset}"] = {
        "position_type": position_type,
        "entry_spread": current_spread,
        "base_position_size": base_asset_position_size,
        "quote_position_size": quote_asset_position_size
    }

  



'''Also use example.py for this one, maybe just change params['side'] to close_long, close_short'''
def exit_trade_pair(base_asset, quote_asset, position_type, open_positions):
  
    # Construct the key from base and quote assets
    key = f"{base_asset}_{quote_asset}"

    # Check if trade exists in open positions
    if key in open_positions:
        trade_info = open_positions[key]
 
    # Unpack values within the open positions dictionary
        position_type = trade_info['position_type']
        base_asset_position_size = trade_info['base_position_size']
        quote_asset_position_size = trade_info['quote_position_size']

        trade_executed = False

        if position_type == "short/long":
            # Close short on base asset
            print(f"Closing short on {base_asset}")
            params_base = {
                "symbol": f"{base_asset}_UMCBL",
                "marginCoin": "USDT",
                "side": "close_short",
                "orderType": "market",
                "size": base_asset_position_size,
                "timInForceValue": "normal"
            }
            # Close long on quote asset
            print(f"Closing long on {quote_asset}")
            params_quote = {
                "symbol": f"{quote_asset}_UMCBL",
                "marginCoin": "USDT",
                "side": "close_long",
                "orderType": "market",
                "size": quote_asset_position_size,
                "timInForceValue": "normal"
            }
        elif position_type == "long/short":
            # Close long on base asset
            print(f"Closing long on {base_asset}")
            params_base = {
                "symbol": f"{base_asset}_UMCBL",
                "marginCoin": "USDT",
                "side": "close_long",
                "orderType": "market",
                "size": base_asset_position_size,
                "timInForceValue": "normal"
            }
            # Close short on quote asset
            print(f"Closing short on {quote_asset}")
            params_quote = {
                "symbol": f"{quote_asset}_UMCBL",
                "marginCoin": "USDT",
                "side": "close_short",
                "orderType": "market",
                "size": quote_asset_position_size,
                "timInForceValue": "normal"
            }

        # Execute the trades
        order_api = maxOrderApi.OrderApi(apiKey, secretKey, passphrase)
        max_retries = 3

        for attempt in range(max_retries):

            try:
                response_base = order_api.placeOrder(params_base)
                print(response_base)
                # Check for success directly after receiving the response
                if response_base.get('code') == '00000' and response_base.get('msg') == 'success':
                    print("Base trade executed successfully.")
                    trade_executed = True
                    break  # Exit the loop if successful
                else:
                    print("Base trade execution failed.")
                    if 'msg' in response_base:
                        print(f"Error message: {response_base['msg']}")
                    if attempt < max_retries:
                        print("Retrying...")
                        time.sleep(1)  # Wait for 1 second before retrying
            except BitgetAPIException as e:
                print("error:" + e.message)
            
        for attempt in range(max_retries):

            try:
                response_quote = order_api.placeOrder(params_quote)
                print(response_quote)
                if response_quote.get('code') == '00000' and response_quote.get('msg') == 'success':
                    print("Quote trade executed successfully.")
                    print(f"Order ID: {response_quote['data']['orderId']}")
                    trade_executed = True
                    break  # Exit the loop if successful
                else:
                    print("Quote trade execution failed.")
                    if 'msg' in response_quote:
                        print(f"Error message: {response_quote['msg']}")
                    if attempt < max_retries:
                        print("Retrying...")
                        time.sleep(1)
            except BitgetAPIException as e:
                print("error:" + e.message)
        
        if trade_executed:
            print(f"Exiting trade: {base_asset}, {quote_asset}")
            return key
        
        
    return None


def manage_close_only_trades(spreads_file, close_only_json):
    if not os.path.exists(spreads_file):
        print(f"Spreads file {spreads_file} not found.")
        return
    close_only_spreads_df = pd.read_csv(spreads_file)


    # Load open positions
    try:
        with open(close_only_json, 'r') as json_file:
            close_only_pairs = json.load(json_file)
    except FileNotFoundError:
        print('No open positions found, starting fresh')
        close_only_pairs = {}

    keys_to_remove = []    

    for market, attributes in close_only_pairs.items():
        print(f"\nProcessing market: {market}")
        base_asset, quote_asset = market.split('_')
        position_type = attributes['position_type']
        WINDOW = 200
        EXIT_Z = 2.0

        calculate_zscore(market, close_only_spreads_df, WINDOW)

        z_score_column = f'z_score_{market}'
        latest_row = close_only_spreads_df.iloc[-1]
        current_z_score = latest_row[z_score_column]
        print (f"z score: {current_z_score}")
        
        key_to_remove = None

        if position_type == "short/long" and current_z_score <= -EXIT_Z:
            print(f"Exiting short/long position for market: {market}")
            key_to_remove = exit_trade_pair(base_asset, quote_asset, position_type, close_only_pairs)
            print(key_to_remove)

        elif position_type == "long/short" and current_z_score >= EXIT_Z:
            print(f"Exiting long/short position for market: {market}")
            key_to_remove = exit_trade_pair(base_asset, quote_asset, position_type, close_only_pairs)
            print(key_to_remove)

        if key_to_remove is not None:
            keys_to_remove.append(key_to_remove)
            print(keys_to_remove)   

    print('Before deletion:', close_only_pairs.keys())
    for key in keys_to_remove:
        if key in close_only_pairs:
            del close_only_pairs[key]
    print('After deletion:', close_only_pairs.keys())

    # Consider persisting open_positions to a file if needed for longer-term tracking beyond script execution
    with open('close_only.json', 'w') as json_file:
        json.dump(close_only_pairs, json_file, indent=4)



def close_all_trades(tradable_pairs_file):
    with open(tradable_pairs_file, 'r') as file:
        close_only_pairs = json.load(file)

    for market, params in list(close_only_pairs.items()):
        base_asset, quote_asset = market.split('_')
        position_info = params
        position_type = position_info["position_type"]

        exit_trade_pair(base_asset, quote_asset, position_type, close_only_pairs)
        time.sleep(0.5)