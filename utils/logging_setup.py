"""
Logging configuration for the Daily Briefing application.

This module sets up logging for the application, including console and file handlers.
"""

import logging
from config import LOG_FILE, PROMPT_LOG_FILE

def setup_logging():
    """
    Configure logging to log to both console and file.
    
    Returns:
        tuple: A tuple containing (main_logger, prompt_logger)
    """
    # Configure main logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_FILE, encoding='utf-8')
        ]
    )
    
    # Create a custom logger for prompts and responses
    prompt_logger = logging.getLogger('prompts')
    prompt_logger.setLevel(logging.INFO)
    
    # Create a separate log file for prompts and LLM outputs
    prompt_file_handler = logging.FileHandler(PROMPT_LOG_FILE, encoding='utf-8')
    prompt_file_handler.setFormatter(logging.Formatter('%(asctime)s\n%(message)s\n'))
    prompt_logger.addHandler(prompt_file_handler)
    
    # Prevent prompt logs from propagating to the root logger
    prompt_logger.propagate = False
    
    return logging.getLogger(), prompt_logger

def log_section_prompt(prompt_logger, section_title, prompt, user_content):
    """
    Log a section prompt to the prompt logger.
    
    Args:
        prompt_logger: The prompt logger instance
        section_title: The title of the section
        prompt: The system prompt
        user_content: The user content
    """
    prompt_logger.info(
        f"\n{'='*80}\nPROMPT FOR {section_title}\n{'='*80}\n"
        f"SYSTEM: {prompt}\n\nUSER: {user_content}\n{'='*80}\n"
    )

def log_section_response(prompt_logger, section_title, response):
    """
    Log a section response to the prompt logger.
    
    Args:
        prompt_logger: The prompt logger instance
        section_title: The title of the section
        response: The response content
    """
    prompt_logger.info(
        f"\n{'='*80}\nRESPONSE FOR {section_title}\n{'='*80}\n"
        f"{response}\n{'='*80}\n"
    )

def log_newsletter(prompt_logger, newsletter):
    """
    Log the generated newsletter to the prompt logger.
    
    Args:
        prompt_logger: The prompt logger instance
        newsletter: The generated newsletter HTML
    """
    prompt_logger.info(
        f"\n{'='*80}\nGENERATED NEWSLETTER\n{'='*80}\n"
        f"{newsletter}\n{'='*80}\n"
    ) 