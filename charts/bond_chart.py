"""
Bond price chart module for the Daily Briefing application.

This module retrieves and processes Beyond Meat bond price data using Selenium.
"""

import logging
import os
import time
from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import BEYOND_MEAT_BOND_URL, BEYOND_MEAT_BOND_CHART_PATH

def get_beyond_meat_bond_chart() -> None:
    """
    Uses Selenium to capture a screenshot of Beyond Meat's bond price chart,
    adds a title, and saves it as an image file.
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

    driver = None
    
    try:
        logging.info("Initializing Chrome driver for Beyond Meat bond chart...")
        driver = webdriver.Chrome(options=chrome_options)
        
        # Navigate to the page
        logging.info(f"Navigating to {BEYOND_MEAT_BOND_URL}...")
        driver.get(BEYOND_MEAT_BOND_URL)
        
        # Wait for the main chart container
        wait = WebDriverWait(driver, 20)
        logging.info("Waiting for chart container to load...")
        chart_container = wait.until(EC.presence_of_element_located((By.ID, "DetailChart")))
        
        # Give the page more time to completely load and render the chart
        time.sleep(5)
        
        # Scroll to make the chart visible before interacting
        driver.execute_script("arguments[0].scrollIntoView(true);", chart_container)
        time.sleep(2)
        
        # Try to select 1Y (1 Year) time period
        try:
            logging.info("Attempting to select 1-year chart view...")
            one_year_tab = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//div[contains(@class, 'tab__item') and text()='1y']")))
            
            # Use JavaScript to click the tab
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
        
        # Add title to the image using PIL
        if os.path.exists(temp_screenshot_path):
            logging.info("Adding title to the bond chart image...")
            # Open the image
            img = Image.open(temp_screenshot_path)
            width, height = img.size
            
            # Create a new image with extra space at the top for the title
            title_height = 50  # Height for the title section
            new_img = Image.new('RGB', (width, height + title_height), color=(255, 255, 255))
            new_img.paste(img, (0, title_height))
            
            # Add title
            draw = ImageDraw.Draw(new_img)
            
            # Try to use a nice font, with fallback to default
            try:
                # Try to find a suitable font - adjust path if needed
                font_paths = [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
                    "/Library/Fonts/Arial Bold.ttf",  # macOS
                    "C:/Windows/Fonts/arialbd.ttf"  # Windows
                ]
                
                font = None
                for path in font_paths:
                    if os.path.exists(path):
                        font = ImageFont.truetype(path, 20)
                        break
                        
                if font is None:
                    # Use default font if none of the specified fonts are found
                    font = ImageFont.load_default()
                    
            except Exception:
                font = ImageFont.load_default()
            
            # Draw the title
            title_text = "Beyond Meat Bond Prices"
            text_width = draw.textlength(title_text, font=font) if hasattr(draw, 'textlength') else font.getlength(title_text)
            position = ((width - text_width) // 2, 10)  # Center the title
            
            # Draw the text - use color matching the financial chart style
            draw.text(position, title_text, fill=(30, 61, 89), font=font)  # Match CHART_COLOR
            
            # Save the new image
            new_img.save(BEYOND_MEAT_BOND_CHART_PATH)
            logging.info(f"Bond chart image with title saved to: {BEYOND_MEAT_BOND_CHART_PATH}")
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