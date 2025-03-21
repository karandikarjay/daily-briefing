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
    api_call: callable,
    resource_type: str = "completions",
    max_retries: int = MAX_RETRIES,
    initial_retry_delay: float = INITIAL_RETRY_DELAY,
    max_retry_delay: float = MAX_RETRY_DELAY
) -> Any:
    """
    Makes an API call to OpenAI with exponential backoff for retries.
    Handles rate limits and token limits.
    
    Args:
        client: The OpenAI client instance
        api_call: A callable that makes the actual API call
        resource_type: The type of resource being requested (completions, images, etc.)
        max_retries: Maximum number of retries
        initial_retry_delay: Initial delay between retries (seconds)
        max_retry_delay: Maximum delay between retries (seconds)
        
    Returns:
        The API response
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            # Add jitter to avoid synchronized retries
            jitter = random.uniform(0.8, 1.2)
            
            # Make the API call
            response = api_call()
            return response
            
        except Exception as e:
            retry_count += 1
            
            # Check if it's a rate limit error
            is_rate_limit = (
                hasattr(e, 'code') and e.code == 'rate_limit_exceeded' or
                hasattr(e, 'status_code') and e.status_code == 429 or
                "rate limit" in str(e).lower()
            )
            
            if is_rate_limit:
                logging.warning(f"{resource_type} rate limit exceeded. Attempt {retry_count}/{max_retries}")
            else:
                logging.warning(f"API error with {resource_type}: {str(e)}. Attempt {retry_count}/{max_retries}")
            
            if retry_count >= max_retries:
                logging.error(f"Max retries reached. Giving up on {resource_type} request.")
                raise
            
            # Calculate backoff with jitter
            delay = min(initial_retry_delay * (2 ** (retry_count - 1)) * jitter, max_retry_delay)
            logging.info(f"Retrying {resource_type} request in {delay:.2f} seconds...")
            time.sleep(delay)
    
    # This should not be reached due to the raise in the loop
    raise Exception(f"Max retries exceeded without successful {resource_type} API call")

def call_stability_api_with_backoff(
    api_call: callable,
    resource_type: str = "stability_image",
    max_retries: int = MAX_RETRIES,
    initial_retry_delay: float = INITIAL_RETRY_DELAY,
    max_retry_delay: float = MAX_RETRY_DELAY
) -> Any:
    """
    Makes an API call to Stability AI with exponential backoff for retries.
    Handles rate limits and errors.
    
    Args:
        api_call: A callable that makes the actual API call
        resource_type: Description of the resource being requested
        max_retries: Maximum number of retries
        initial_retry_delay: Initial delay between retries (seconds)
        max_retry_delay: Maximum delay between retries (seconds)
        
    Returns:
        The API response
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            # Add jitter to avoid synchronized retries
            jitter = random.uniform(0.8, 1.2)
            
            # Make the API call
            response = api_call()
            
            # Check the status code
            if response.status_code in [200, 201, 202]:
                return response
            else:
                # Handle non-success status codes
                error_message = str(response.json()) if response.headers.get('content-type') == 'application/json' else f"Status code: {response.status_code}"
                raise Exception(f"Stability API error: {error_message}")
            
        except Exception as e:
            retry_count += 1
            
            # Check if it's a rate limit error
            is_rate_limit = (
                hasattr(e, 'status_code') and e.status_code == 429 or
                "rate limit" in str(e).lower() or
                "too many requests" in str(e).lower()
            )
            
            if is_rate_limit:
                logging.warning(f"{resource_type} rate limit exceeded. Attempt {retry_count}/{max_retries}")
            else:
                logging.warning(f"API error with {resource_type}: {str(e)}. Attempt {retry_count}/{max_retries}")
            
            if retry_count >= max_retries:
                logging.error(f"Max retries reached. Giving up on {resource_type} request.")
                raise
            
            # Calculate backoff with jitter
            delay = min(initial_retry_delay * (2 ** (retry_count - 1)) * jitter, max_retry_delay)
            logging.info(f"Retrying {resource_type} request in {delay:.2f} seconds...")
            time.sleep(delay)
    
    # This should not be reached due to the raise in the loop
    raise Exception(f"Max retries exceeded without successful {resource_type} API call")

def call_openai_api_with_messages(
    client: OpenAI,
    messages: List[Dict[str, str]],
    model: str = AI_MODEL,
    max_tokens: int = None,
    response_format: Dict[str, str] = None
) -> Any:
    """
    Makes an API call to OpenAI with exponential backoff for retries.
    Handles rate limits and token limits. Specifically for chat completions.
    
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
    
    # Make the API call with backoff
    return call_openai_api_with_backoff(
        client,
        api_call=lambda: client.chat.completions.create(**params),
        resource_type="completions"
    )

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
    
    # Make the parse API call with backoff
    return call_openai_api_with_backoff(
        client,
        api_call=lambda: client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_model
        ),
        resource_type="completions"
    ) 