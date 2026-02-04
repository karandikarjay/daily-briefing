"""
Email content retrieval module for the Daily Briefing application.

This module provides functions for retrieving content from email sources.
"""

import logging
import imaplib
import email
import re
from email.header import decode_header
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Dict
from config import GOOGLE_USERNAME, GOOGLE_PASSWORD, IMAP_SERVER, IMAP_PORT, FAST_EMAILS, TIMEZONE
from utils.api_utils import get_content_collection_timeframe
from datetime import timezone

def get_fast_email_content() -> List[Dict[str, str]]:
    """
    Connects to the Gmail IMAP server and retrieves emails that include the specified email addresses
    (FAST email lists) in any "to" or "from" field within the configured time window.
    
    Returns:
        List[Dict[str, str]]: A list of email contents with subject, body, and datetime
    """
    try:
        start_time, end_time = get_content_collection_timeframe()
        
        logging.info(f"FAST: Retrieving emails from {start_time} to {end_time}")
        
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(GOOGLE_USERNAME, GOOGLE_PASSWORD)
        mail.select("inbox")

        # Convert the start and end dates to the format required by IMAP (DD-MMM-YYYY)
        start_date_str = start_time.strftime("%d-%b-%Y")
        end_date_str = end_time.strftime("%d-%b-%Y")

        # Create IMAP search criteria to get emails only from the specific timeframe
        # SINCE <date> BEFORE <date+1> gets emails from a specific date
        # We'll use SINCE start_date BEFORE end_date+1 to cover the full range
        next_day_after_end = (end_time + timedelta(days=1)).strftime("%d-%b-%Y")
        
        # IMAP OR can only operate on two conditions at a time
        # We'll build our criteria differently for proper OR operations
        date_criteria = f'SINCE {start_date_str} BEFORE {next_day_after_end}'
        
        # For a single email address, the search is straightforward
        if len(FAST_EMAILS) == 1:
            email_addr = FAST_EMAILS[0]
            search_criteria = f'({date_criteria}) (OR (TO "{email_addr}") (FROM "{email_addr}"))'
        else:
            # For multiple addresses, we need to build a series of nested OR conditions
            # Start with the first email address
            email_conditions = f'OR (TO "{FAST_EMAILS[0]}") (FROM "{FAST_EMAILS[0]}")'
            
            # Add other email addresses with nested OR conditions
            for email_addr in FAST_EMAILS[1:]:
                email_conditions = f'OR ({email_conditions}) (OR (TO "{email_addr}") (FROM "{email_addr}"))'
            
            # Combine date criteria with email conditions
            search_criteria = f'({date_criteria}) ({email_conditions})'
        
        logging.info(f"IMAP search criteria: {search_criteria}")
        status, data = mail.search(None, search_criteria)
        
        email_ids = data[0].split()
        logging.info(f"Found {len(email_ids)} emails matching the date and address criteria")

        emails_content = []

        # Process each email that matches our criteria
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    # Get the internal date when the email was received by the server
                    # This is more reliable than the Date header
                    status, internal_date_data = mail.fetch(email_id, "(INTERNALDATE)")
                    
                    # Parse the INTERNALDATE from the response
                    internal_date_str = internal_date_data[0].decode()
                    match = re.search(r'INTERNALDATE "([^"]+)"', internal_date_str)
                    
                    if match:
                        # Convert the INTERNALDATE string to a datetime object
                        internal_date_str = match.group(1)
                        try:
                            # Parse the date in the format like "01-Jan-2023 12:34:56 +0000"
                            date_tuple = datetime.strptime(internal_date_str, "%d-%b-%Y %H:%M:%S %z")
                        except ValueError:
                            # Fallback to Date header if parsing fails
                            date_tuple = parsedate_to_datetime(msg["Date"])
                    else:
                        # Fallback to Date header if INTERNALDATE not available
                        date_tuple = parsedate_to_datetime(msg["Date"])
                    
                    if date_tuple.tzinfo is None:
                        date_tuple = date_tuple.replace(tzinfo=timezone.utc)
                    date_tuple = date_tuple.astimezone(TIMEZONE)
                    
                    # Double-check the date is in our range (in case IMAP search wasn't precise enough)
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
                                        "datetime": date_tuple.isoformat(),
                                        "source_name": "FAST Email List"
                                    })
                        else:
                            body = msg.get_payload(decode=True).decode()
                            emails_content.append({
                                "subject": subject, 
                                "body": body,
                                "datetime": date_tuple.isoformat(),
                                "source_name": "FAST Email List"
                            })

        mail.logout()
        logging.info(f"Retrieved {len(emails_content)} FAST emails in the configured time window")
        return emails_content

    except Exception as e:
        logging.exception("Error retrieving FAST email content")
        return [] 