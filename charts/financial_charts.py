"""
Financial charts module for the Daily Briefing application.

This module provides functions for creating financial charts for the daily briefing.
"""

import logging
import matplotlib.pyplot as plt
import yfinance as yf
import pandas as pd
from config import TICKERS, CHART_STYLE, CHART_COLOR, GRID_COLOR, BACKGROUND_COLOR, CHART_DPI

def create_charts() -> None:
    """
    Creates charts for a set of financial tickers using yfinance data.
    Saves the charts as image files.
    """
    plt.style.use(CHART_STYLE)

    for ticker, info in TICKERS.items():
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
                 label='Close Price' if ticker != '^TNX' else 'Yield',
                 color=CHART_COLOR, linewidth=2)
        plt.grid(True, linestyle='--', alpha=0.7, color=GRID_COLOR)
        
        # Annotate the most recent price
        latest_date = data.index[-1]
        latest_price = data['Close'].iloc[-1][ticker]
        plt.annotate(f'{latest_price:.2f}',
                     xy=(latest_date, latest_price),
                     xytext=(latest_date + pd.Timedelta(days=2), latest_price),
                     fontsize=14, color=CHART_COLOR,
                     ha='left', va='center')

        # Customize title based on ticker
        if ticker == '^TNX':
            title = f"{info['display_name']} Yield"
        else:
            title = f"{info['display_name']}"
            
        plt.title(title, color=CHART_COLOR, fontsize=18, pad=20, fontweight='bold')
        
        ax.tick_params(colors=CHART_COLOR, labelsize=12)
        plt.tight_layout()
        plt.savefig(info['filename'], dpi=CHART_DPI, bbox_inches='tight', facecolor=BACKGROUND_COLOR)
        plt.close()
        logging.info(f"Saved chart: {info['filename']}") 