"""
Email content retrieval module for the Daily Briefing application.

This module provides functions for retrieving content from email sources.
"""

import logging
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Dict
from config import GOOGLE_USERNAME, GOOGLE_PASSWORD, IMAP_SERVER, IMAP_PORT, FAST_EMAIL
from utils.api_utils import get_content_collection_timeframe

def get_fast_email_content() -> List[Dict[str, str]]:
    """
    Connects to the Gmail IMAP server and retrieves emails that include the specified email
    (FAST email list) in any "to" or "from" field within the configured time window.
    
    Returns:
        List[Dict[str, str]]: A list of email contents with subject, body, and datetime
    """
    search_email = FAST_EMAIL
    
    try:
        start_time, end_time = get_content_collection_timeframe()
        
        logging.info(f"FAST: Retrieving emails from {start_time} to {end_time}")
        
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(GOOGLE_USERNAME, GOOGLE_PASSWORD)
        mail.select("inbox")

        # Calculate the date for search (two weeks ago initially to get enough emails to filter)
        two_weeks_ago = (end_time - timedelta(weeks=2)).strftime("%d-%b-%Y")

        # Search for emails that include the specified email in any "to" or "from" field within the past two weeks
        status, data = mail.search(None, f'(OR (TO "{search_email}" SINCE {two_weeks_ago}) (FROM "{search_email}" SINCE {two_weeks_ago}))')
        email_ids = data[0].split()

        emails_content = []

        # Fetch emails within the time window
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    date_tuple = parsedate_to_datetime(msg["Date"])
                    
                    if start_time <= date_tuple <= end_time:
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding if encoding else "utf-8")

                        # Remove 'FAST ♞ ' from the subject if present
                        subject = subject.replace('FAST ♞ ', '')

                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                if content_type == "text/plain":
                                    body = part.get_payload(decode=True).decode()
                                    emails_content.append({
                                        "subject": subject, 
                                        "body": body,
                                        "datetime": date_tuple
                                    })
                        else:
                            body = msg.get_payload(decode=True).decode()
                            emails_content.append({
                                "subject": subject, 
                                "body": body,
                                "datetime": date_tuple
                            })

        mail.logout()
        logging.info(f"Retrieved {len(emails_content)} FAST emails in the configured time window")
        return emails_content

    except Exception as e:
        logging.exception("Error retrieving FAST email content")
        return [] 