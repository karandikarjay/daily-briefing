"""
Financial charts module for the Daily Briefing application.

This module provides functions for creating financial charts for the daily briefing.
"""

import logging
import time
import matplotlib.pyplot as plt
from charts.style import finish_chart
import yfinance as yf
import pandas as pd
from config import TICKERS, CHART_STYLE, CHART_COLOR, GRID_COLOR, BACKGROUND_COLOR, CHART_DPI

# Delay between Yahoo Finance API calls to avoid rate limiting
YF_REQUEST_DELAY = 2  # seconds

def create_charts() -> None:
    """
    Creates charts for a set of financial tickers using yfinance data.
    Saves the charts as image files with informative titles.
    """
    plt.style.use(CHART_STYLE)

    for i, (ticker, info) in enumerate(TICKERS.items()):
        # Add delay between requests to avoid Yahoo Finance rate limiting
        if i > 0:
            logging.info(f"Waiting {YF_REQUEST_DELAY}s before next request to avoid rate limiting...")
            time.sleep(YF_REQUEST_DELAY)

        logging.info(f"Downloading data for {info['display_name']}...")
        data = yf.download(ticker, period="1y")
        if data.empty:
            logging.warning(f"No data found for {info['display_name']}. Skipping chart creation.")
            continue

        logging.info(f"Plotting chart for {info['display_name']}...")
        plt.figure(figsize=(10, 6), facecolor=BACKGROUND_COLOR)
        ax = plt.gca()
        ax.set_facecolor(BACKGROUND_COLOR)
        plt.plot(data.index, data['Close'],
                 label='Close Price',
                 color=CHART_COLOR, linewidth=2)
        plt.grid(True, linestyle='--', alpha=0.7, color=GRID_COLOR)
        
        # Annotate the most recent price
        latest_date = data.index[-1]
        # The line below is not an error
        # data['Close'].iloc[-1] is a Series
        latest_price = data['Close'].iloc[-1][ticker]
        plt.annotate(f'{latest_price:.2f}',
                     xy=(latest_date, latest_price),
                     xytext=(latest_date + pd.Timedelta(days=2), latest_price),
                     fontsize=14, color=CHART_COLOR,
                     ha='left', va='center')

        finish_chart(ax, info['filename'])
        plt.close()
        logging.info(f"Saved chart: {info['filename']}") 