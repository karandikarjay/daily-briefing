"""
Bond price chart module for the Daily Briefing application.

This module retrieves and processes Beyond Meat bond price data using Selenium.
"""

import logging
import os
import time
from charts.style import transparent_screenshot
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import BEYOND_MEAT_BOND_URL, BEYOND_MEAT_BOND_CHART_PATH

def get_beyond_meat_bond_chart() -> None:
    """
    Uses Selenium to capture a screenshot of Beyond Meat's bond price chart,
    removes the white matte, and saves a transparent image file.
    """
    temp_screenshot_path = os.path.join(os.path.dirname(BEYOND_MEAT_BOND_CHART_PATH), "chart_only.png")
    
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--enable-unsafe-swiftshader")
    chrome_options.add_argument("--blink-settings=imagesEnabled=true")
    chrome_options.page_load_timeout = 60

    driver = None

    try:
        logging.info("Initializing Chrome driver for Beyond Meat bond chart...")
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(60)

        # Navigate to the page
        logging.info(f"Navigating to {BEYOND_MEAT_BOND_URL}...")
        driver.get(BEYOND_MEAT_BOND_URL)
        
        wait = WebDriverWait(driver, 30)
        logging.info("Waiting for chart container to load...")
        chart_container = wait.until(EC.presence_of_element_located((By.ID, "DetailChart")))

        # Brief pause for chart JS to initialize, then scroll into view
        time.sleep(3)
        driver.execute_script("arguments[0].scrollIntoView(true);", chart_container)
        time.sleep(2)

        # Try to select 1Y (1 Year) time period
        try:
            logging.info("Attempting to select 1-year chart view...")
            one_year_tab = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class, 'tab__item') and text()='1y']")))

            driver.execute_script("arguments[0].click();", one_year_tab)
            time.sleep(3)  # Wait for the chart to update
        except Exception as e:
            logging.warning(f"Could not click 1y tab: {e}")
        
        # Find the actual chart canvas element
        try:
            logging.info("Taking screenshot of chart canvas...")
            chart_canvas = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//app-detail-chart//canvas")))
            
            # Take a screenshot of just the chart canvas
            chart_canvas.screenshot(temp_screenshot_path)
            logging.info("Chart screenshot successfully taken!")
        except Exception as e:
            logging.warning(f"Error finding chart canvas: {e}")
            
            # Fallback: try to get the chart area with a more specific selector
            try:
                chart_area = wait.until(EC.presence_of_element_located((By.XPATH, "//app-detail-chart//div[@class='chartContainer']")))
                chart_area.screenshot(temp_screenshot_path)
                logging.info("Chart area screenshot taken as fallback!")
            except Exception as e:
                logging.warning(f"Error with fallback chart area: {e}")
                # Last resort: take a screenshot of the whole chart container
                chart_container.screenshot(temp_screenshot_path)
                logging.info("Chart container screenshot taken as last resort!")
        
        if os.path.exists(temp_screenshot_path):
            transparent_screenshot(temp_screenshot_path, BEYOND_MEAT_BOND_CHART_PATH)
            logging.info("Saved transparent bond chart: %s", BEYOND_MEAT_BOND_CHART_PATH)
        else:
            logging.error(f"Error: Screenshot file {temp_screenshot_path} not found")
        
    except Exception as e:
        logging.exception(f"Error capturing Beyond Meat bond chart: {e}")
    finally:
        if driver:
            driver.quit()
        # Clean up temporary screenshot
        if os.path.exists(temp_screenshot_path):
            os.remove(temp_screenshot_path) 