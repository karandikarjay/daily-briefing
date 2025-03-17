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

def get_fast_email_content() -> List[Dict[str, str]]:
    """
    Connects to the Gmail IMAP server and retrieves emails that include the specified email
    (FAST email list) in any "to" or "from" field for the last 24 hours from the most recent email.
    
    Returns:
        List[Dict[str, str]]: A list of email contents with subject and body
    """
    search_email = FAST_EMAIL

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(GOOGLE_USERNAME, GOOGLE_PASSWORD)
        mail.select("inbox")

        # Calculate the date two weeks ago (for initial search)
        two_weeks_ago = (datetime.now() - timedelta(weeks=2)).strftime("%d-%b-%Y")

        # Search for emails that include the specified email in any "to" or "from" field within the past two weeks
        status, data = mail.search(None, f'(OR (TO "{search_email}" SINCE {two_weeks_ago}) (FROM "{search_email}" SINCE {two_weeks_ago}))')
        email_ids = data[0].split()

        latest_datetime = None
        email_dates = []

        # First pass: find the most recent email timestamp
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(BODY.PEEK[HEADER])")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    date_tuple = parsedate_to_datetime(msg["Date"])
                    if latest_datetime is None or date_tuple > latest_datetime:
                        latest_datetime = date_tuple

        if latest_datetime is None:
            logging.error("No valid timestamps found in FAST emails")
            return []

        # Calculate the cutoff time (24 hours before the most recent email)
        cutoff_time = latest_datetime - timedelta(hours=24)
        logging.info(f"FAST: Using emails between {cutoff_time} and {latest_datetime}")

        emails_content = []

        # Second pass: fetch emails within the 24-hour window
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    date_tuple = parsedate_to_datetime(msg["Date"])
                    
                    if cutoff_time <= date_tuple <= latest_datetime:
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
                                    emails_content.append({"subject": subject, "body": body})
                        else:
                            body = msg.get_payload(decode=True).decode()
                            emails_content.append({"subject": subject, "body": body})

        mail.logout()
        logging.info(f"Retrieved {len(emails_content)} FAST emails in the last 24 hours")
        return emails_content

    except Exception as e:
        logging.exception("Error retrieving FAST email content")
        return [] 