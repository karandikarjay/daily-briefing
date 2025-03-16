"""
Email utilities for the Daily Briefing application.

This module provides functions for sending emails with the daily briefing content.
"""

import logging
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from typing import List, Optional
from datetime import datetime
from config import (
    GOOGLE_USERNAME, GOOGLE_PASSWORD, RECIPIENT_EMAILS,
    SMTP_SERVER, SMTP_PORT, CHART_PATHS, CHART_CONTENT_IDS,
    EASTERN_ZONE
)

def send_email(html_content: str, send_to_everyone: bool = False) -> bool:
    """
    Sends an email with the daily briefing content.
    
    Args:
        html_content (str): The HTML content of the email
        send_to_everyone (bool): Whether to send to all recipients or just the sender
        
    Returns:
        bool: True if the email was sent successfully, False otherwise
    """
    # Get today's date in Eastern Time
    today = datetime.now(EASTERN_ZONE).strftime("%A, %B %d, %Y")
    subject = f"Daily Briefing - {today}"
    
    # Determine recipients based on the send_to_everyone flag
    recipients = [GOOGLE_USERNAME]
    bcc_recipients = RECIPIENT_EMAILS if send_to_everyone else []
    
    try:
        # Create message container
        msg = MIMEMultipart('related')
        msg['Subject'] = subject
        msg['From'] = GOOGLE_USERNAME
        msg['To'] = GOOGLE_USERNAME
        if bcc_recipients:
            msg['Bcc'] = ", ".join(bcc_recipients)
        
        # Attach HTML content
        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        
        # Create HTML part
        html_part = MIMEText(html_content, 'html')
        msg_alternative.attach(html_part)
        
        # Attach images
        for image_path, content_id in CHART_CONTENT_IDS.items():
            full_path = CHART_PATHS.get(image_path)
            if full_path and os.path.exists(full_path):
                with open(full_path, 'rb') as img_file:
                    img = MIMEImage(img_file.read())
                    img.add_header('Content-ID', content_id)
                    img.add_header('Content-Disposition', 'inline', filename=image_path)
                    msg.attach(img)
            else:
                logging.warning(f"Image file not found: {full_path}")
        
        # Connect to SMTP server
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(GOOGLE_USERNAME, GOOGLE_PASSWORD)
        
        # Send email - include both To and Bcc recipients in the sendmail call
        all_recipients = recipients + bcc_recipients
        server.sendmail(GOOGLE_USERNAME, all_recipients, msg.as_string())
        server.quit()
        
        logging.info(f"Email sent successfully to {len(all_recipients)} recipient(s)")
        return True
        
    except Exception as e:
        logging.exception(f"Error sending email: {str(e)}")
        return False 