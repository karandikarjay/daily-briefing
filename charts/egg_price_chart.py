"""
Egg price chart module for the Daily Briefing application.

This module retrieves average US egg prices from FRED (Federal Reserve Economic Data)
and generates a matplotlib chart matching the style of the stock charts.
"""

import logging
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
from config import EGG_PRICE_CHART_PATH, CHART_STYLE, CHART_COLOR, GRID_COLOR, BACKGROUND_COLOR, CHART_DPI

# FRED series: Average Price, Eggs, Grade A, Large ($/dozen), monthly
FRED_EGG_SERIES_BASE_URL = (
    "https://fred.stlouisfed.org/graph/fredgraph.csv"
    "?id=APU0000708111"
)


def extract_egg_price_chart() -> None:
    """
    Downloads egg price data from FRED and generates a chart
    in the same style as the stock price charts.
    """
    try:
        logging.info("Downloading egg price data from FRED...")
        one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        url = f"{FRED_EGG_SERIES_BASE_URL}&cosd={one_year_ago}"
        df = pd.read_csv(url, parse_dates=["observation_date"])
        df = df.rename(columns={"observation_date": "date", "APU0000708111": "price"})
        df = df.dropna(subset=["price"])

        if df.empty:
            logging.warning("No egg price data returned from FRED. Skipping chart.")
            return

        logging.info(f"FRED egg prices: {len(df)} data points from {df['date'].iloc[0].date()} to {df['date'].iloc[-1].date()}")

        plt.style.use(CHART_STYLE)
        plt.figure(figsize=(10, 6), facecolor=BACKGROUND_COLOR)
        ax = plt.gca()
        ax.set_facecolor(BACKGROUND_COLOR)

        plt.plot(df["date"], df["price"], color=CHART_COLOR, linewidth=2)
        plt.grid(True, linestyle="--", alpha=0.7, color=GRID_COLOR)

        # Annotate the most recent price
        latest_date = df["date"].iloc[-1]
        latest_price = df["price"].iloc[-1]
        plt.annotate(
            f"${latest_price:.2f}",
            xy=(latest_date, latest_price),
            xytext=(latest_date + pd.Timedelta(days=8), latest_price),
            fontsize=14,
            color=CHART_COLOR,
            ha="left",
            va="center",
        )

        plt.title("US Egg Prices ($/dozen)", color=CHART_COLOR, fontsize=18, pad=20, fontweight="bold")
        ax.tick_params(colors=CHART_COLOR, labelsize=12)
        plt.tight_layout()
        plt.savefig(EGG_PRICE_CHART_PATH, dpi=CHART_DPI, bbox_inches="tight", facecolor=BACKGROUND_COLOR)
        plt.close()

        logging.info(f"Egg price chart saved to: {EGG_PRICE_CHART_PATH}")

    except Exception as e:
        logging.exception(f"Error generating egg price chart: {e}")
