"""
API utilities for the Daily Briefing application.

This module provides functions for interacting with the OpenAI API,
including rate limiting, retries, and token counting.
"""

import logging
import random
import time
import tiktoken
from typing import List, Dict, Any, Type
from openai import OpenAI
from pydantic import BaseModel
from config import AI_MODEL, MAX_RETRIES, INITIAL_RETRY_DELAY, MAX_RETRY_DELAY, MAX_TOKENS_PER_REQUEST

def num_tokens_from_string(string: str, model: str = "gpt-4") -> int:
    """
    Returns the number of tokens in a text string.
    
    Args:
        string: The string to count tokens for
        model: The model to use for token counting
        
    Returns:
        int: The number of tokens in the string
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(string))
    except Exception as e:
        logging.warning(f"Error counting tokens: {e}. Using approximate count.")
        # Fallback to approximate count (1 token ≈ 4 chars for English text)
        return len(string) // 4

def call_openai_api_with_backoff(
    client: OpenAI,
    messages: List[Dict[str, str]],
    model: str = AI_MODEL,
    max_tokens: int = None,
    response_format: Dict[str, str] = None
) -> Any:
    """
    Makes an API call to OpenAI with exponential backoff for retries.
    Handles rate limits and token limits.
    
    Args:
        client: The OpenAI client instance
        messages: List of message dictionaries to send
        model: The model to use (default: AI_MODEL)
        max_tokens: Maximum tokens for the response (optional)
        response_format: Format specification for the response (optional)
        
    Returns:
        The API response
    """
    # Count tokens in the request
    total_tokens = sum(num_tokens_from_string(msg["content"]) for msg in messages)
    
    if total_tokens > MAX_TOKENS_PER_REQUEST:
        logging.warning(f"Request too large ({total_tokens} tokens). This may exceed rate limits.")
    
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Add jitter to avoid synchronized retries
            jitter = random.uniform(0.8, 1.2)
            
            # Prepare the API call parameters
            params = {
                "messages": messages,
                "model": model
            }
            
            # Add optional parameters if provided
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
                
            if response_format is not None:
                params["response_format"] = response_format
            
            # Make the API call
            response = client.chat.completions.create(**params)
            return response
        except Exception as e:
            retry_count += 1
            
            # Check if it's a rate limit error
            if hasattr(e, 'code') and e.code == 'rate_limit_exceeded':
                logging.warning(f"Rate limit exceeded. Attempt {retry_count}/{MAX_RETRIES}")
            else:
                logging.warning(f"API error: {str(e)}. Attempt {retry_count}/{MAX_RETRIES}")
            
            if retry_count >= MAX_RETRIES:
                logging.error(f"Max retries reached. Giving up.")
                raise
            
            # Calculate backoff with jitter
            delay = min(INITIAL_RETRY_DELAY * (2 ** (retry_count - 1)) * jitter, MAX_RETRY_DELAY)
            logging.info(f"Retrying in {delay:.2f} seconds...")
            time.sleep(delay)
    
    # This should not be reached due to the raise in the loop
    raise Exception("Max retries exceeded without successful API call")

def call_openai_parse_with_backoff(
    client: OpenAI,
    messages: List[Dict[str, str]],
    response_model: Type[BaseModel],
    model: str = AI_MODEL
) -> Any:
    """
    Makes a parse API call to OpenAI with exponential backoff for retries.
    This is specifically for structured data parsing using client.beta.chat.completions.parse
    
    Args:
        client: The OpenAI client instance
        messages: List of message dictionaries to send
        response_model: Pydantic model to parse the response into
        model: The model to use (default: AI_MODEL)
        
    Returns:
        The parsed API response
    """
    # Count tokens in the request
    total_tokens = sum(num_tokens_from_string(msg["content"]) for msg in messages)
    
    if total_tokens > MAX_TOKENS_PER_REQUEST:
        logging.warning(f"Request too large ({total_tokens} tokens). This may exceed rate limits.")
    
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Add jitter to avoid synchronized retries
            jitter = random.uniform(0.8, 1.2)
            
            # Make the parse API call
            response = client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=response_model
            )
            return response
        except Exception as e:
            retry_count += 1
            
            # Check if it's a rate limit error
            if hasattr(e, 'code') and e.code == 'rate_limit_exceeded':
                logging.warning(f"Rate limit exceeded. Attempt {retry_count}/{MAX_RETRIES}")
            else:
                logging.warning(f"API error: {str(e)}. Attempt {retry_count}/{MAX_RETRIES}")
            
            if retry_count >= MAX_RETRIES:
                logging.error(f"Max retries reached. Giving up.")
                raise
            
            # Calculate backoff with jitter
            delay = min(INITIAL_RETRY_DELAY * (2 ** (retry_count - 1)) * jitter, MAX_RETRY_DELAY)
            logging.info(f"Retrying in {delay:.2f} seconds...")
            time.sleep(delay)
    
    # This should not be reached due to the raise in the loop
    raise Exception("Max retries exceeded without successful API call") 