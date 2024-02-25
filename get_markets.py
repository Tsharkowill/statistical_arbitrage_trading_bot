import pandas as pd
import numpy as np
import time

import bitget.v1.mix.order_api as maxOrderApi
import bitget.v1.mix.market_api as maxMarketApi
from bitget.bitget_api import BitgetApi
from bitget.exceptions import BitgetAPIException

from decouple import config
from functions import to_unix_milliseconds, get_unix_times

if __name__ == '__main__':

    apiKey = config('apiKey')
    secretKey = config('secretKey')
    passphrase = config('passphrase')

    # Create an instance of the BitgetApi class
    baseApi = BitgetApi(apiKey, secretKey, passphrase)

# Maybe make list of market pairs to get data for and create a for loop to iterate through, appending on to the same csv
# Make ["symbol"] and iterable
# Also use the get_unix_times function to grab more data for each trading pair finally append each new pair as
# a new column on to the data frame
# afterwards the csv will be used to find cointegrated pairs or maybe it just remains a dataframe then coint pairs are the csv
# 20 requests per second is the rate limit
    
    
    markets = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "EOSUSDT", "BCHUSDT", "LTCUSDT", "ADAUSDT", "ETCUSDT", "LINKUSDT", "DOGEUSDT", "SOLUSDT", "MATICUSDT", "BNBUSDT", "UNIUSDT", "ICPUSDT", "AAVEUSDT", "XLMUSDT", "ATOMUSDT", "XTZUSDT", "SUSHIUSDT", "AXSUSDT", "THETAUSDT", "AVAXUSDT", "SHIBUSDT", "MANAUSDT", "GALAUSDT", "SANDUSDT", "DYDXUSDT", "CRVUSDT"]

# Send get request
    # try:
    #     params = {}
    #     params["symbol"] = markets[0]
    #     params["productType"] = "USDT-FUTURES"
    #     params["granularity"] = "1H"
    #     print(params)
    #     response = baseApi.get("/api/v2/mix/market/history-candles", params)
    #     df = pd.DataFrame(response)
    #     df['time'] = df['data'].apply(lambda x: x[0])
    #     df['time'] = pd.to_numeric(df['time'])
    #     df['time'] = pd.to_datetime(df['time'], unit='ms')
    #     df['BTCUSDT'] = df['data'].apply(lambda x: x[4])
    #     df = df.drop(['code', 'msg', 'requestTime', 'data'], axis=1)
    #     df.to_csv('data.csv', index=False)
    # except BitgetAPIException as e:
    #     print("error:" + e.message)

    

    # Initialize an empty DataFrame for the final result
    final_df = pd.DataFrame()

    try:
        for market in markets:
            params = {
                "symbol": market,
                "productType": "USDT-FUTURES",
                "granularity": "1H"
            }
            print(params)
            response = baseApi.get("/api/v2/mix/market/history-candles", params)
            
            # Temporary DataFrame from the response
            temp_df = pd.DataFrame(response)
            
            # Process the 'time' column
            temp_df['time'] = temp_df['data'].apply(lambda x: x[0])
            temp_df['time'] = pd.to_numeric(temp_df['time'])
            temp_df['time'] = pd.to_datetime(temp_df['time'], unit='ms')
            
            # Create a new column for the market using the exit price (assuming index 4 is the exit price)
            final_df[market] = temp_df['data'].apply(lambda x: x[4])
            
            # Ensure the 'time' column is synchronized across all market columns
            if 'time' not in final_df.columns:
                final_df['time'] = temp_df['time']

            # Sleep to avoid hitting the rate limit
            time.sleep(0.5)  
        
        # Reorder the DataFrame columns to have 'time' as the first column
        cols = ['time'] + [col for col in final_df.columns if col != 'time']
        final_df = final_df[cols]
        
        # Export the compiled data to a CSV file
        final_df.to_csv('data.csv', index=False)

    except BitgetAPIException as e:
        print(f"error: {e.message}")


