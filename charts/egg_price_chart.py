"""
Egg price chart module for the Daily Briefing application.

This module retrieves and processes USDA egg price data from a PDF report.
"""

import logging
import os
import requests
import fitz  # PyMuPDF
from PIL import Image
from config import USDA_PDF_URL, EGG_PRICE_CHART_PATH

def extract_egg_price_chart() -> None:
    """
    Downloads the USDA egg price PDF report, extracts the price graph,
    and saves it as an image file.
    """
    try:
        # Create a temporary file path for the PDF
        pdf_path = os.path.join(os.path.dirname(EGG_PRICE_CHART_PATH), "temp_usda_report.pdf")
        
        # Download the PDF file
        logging.info(f"Downloading USDA egg price PDF from {USDA_PDF_URL}...")
        response = requests.get(USDA_PDF_URL)
        
        if response.status_code != 200:
            logging.error(f"Failed to download PDF. Status code: {response.status_code}")
            return
            
        # Save the PDF temporarily
        with open(pdf_path, "wb") as f:
            f.write(response.content)
        
        logging.info(f"PDF downloaded successfully to {pdf_path}")
        
        # Open the PDF
        pdf_document = fitz.open(pdf_path)
        
        # Get the first page
        first_page = pdf_document[0]
        
        # Render the page to an image with a higher resolution
        pix = first_page.get_pixmap(matrix=fitz.Matrix(3, 3))  # 3x zoom for better quality
        
        # Convert to PIL Image
        img_data = pix.samples
        img = Image.frombytes("RGB", [pix.width, pix.height], img_data)
        
        # Crop box (left, upper, right, lower) for the price graph
        crop_box = (1150, 245, 2250, 600)  # Adjusted to capture full chart including y-axis labels
        
        # Crop the image
        cropped_image = img.crop(crop_box)
        
        # Save the cropped image
        cropped_image.save(EGG_PRICE_CHART_PATH)
        
        # Clean up
        pdf_document.close()
        
        # Remove temporary PDF file
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            
        logging.info(f"USDA egg price chart extracted and saved to: {EGG_PRICE_CHART_PATH}")
        
    except Exception as e:
        logging.exception(f"Error extracting egg price chart: {e}") 