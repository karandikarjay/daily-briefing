"""
API utilities for the Daily Briefing application.

This module provides functions for interacting with the Anthropic API (Claude)
and OpenAI API (for image generation), including rate limiting, retries, and token counting.
"""

import logging
import random
import time
import json
from typing import List, Dict, Any, Type
from openai import OpenAI
from anthropic import Anthropic
from pydantic import BaseModel
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import (
    AI_MODEL, MAX_RETRIES, INITIAL_RETRY_DELAY, MAX_RETRY_DELAY,
    MAX_TOKENS_PER_REQUEST, TIMEZONE, IMAGE_MODEL, IMAGE_SIZE,
    IMAGE_QUALITY, IMAGE_OUTPUT_FORMAT, MAX_OUTPUT_TOKENS
)

def num_tokens_from_string(string: str, model: str = "claude-opus-4-5-20251101") -> int:
    """
    Returns an approximate number of tokens in a text string.

    Args:
        string: The string to count tokens for
        model: The model to use for token counting (not used for Claude, approximate)

    Returns:
        int: The approximate number of tokens in the string
    """
    # Claude uses approximately 4 characters per token for English text
    # This is a rough approximation
    return len(string) // 4

def call_api_with_backoff(
    api_call: callable,
    resource_type: str = "completions",
    max_retries: int = MAX_RETRIES,
    initial_retry_delay: float = INITIAL_RETRY_DELAY,
    max_retry_delay: float = MAX_RETRY_DELAY
) -> Any:
    """
    Makes an API call with exponential backoff for retries.
    Handles rate limits and errors.

    Args:
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
                hasattr(e, 'status_code') and e.status_code == 429 or
                "rate limit" in str(e).lower() or
                "rate_limit" in str(e).lower()
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

# Keep OpenAI client for image generation
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
    Used for image generation.
    """
    return call_api_with_backoff(
        api_call=api_call,
        resource_type=resource_type,
        max_retries=max_retries,
        initial_retry_delay=initial_retry_delay,
        max_retry_delay=max_retry_delay
    )

def call_openai_image_generation(
    client: OpenAI,
    prompt: str,
    model: str = IMAGE_MODEL,
    size: str = IMAGE_SIZE,
    quality: str = IMAGE_QUALITY,
    output_format: str = IMAGE_OUTPUT_FORMAT
) -> bytes:
    """
    Generates an image using OpenAI's gpt-image-1.5 model with exponential backoff for retries.

    Args:
        client: The OpenAI client instance
        prompt: Text description of the image to generate
        model: The image model to use (default: gpt-image-1.5)
        size: Image size (default: 1536x1024 for landscape)
        quality: Image quality - low, medium, or high (default: medium)
        output_format: Output format - png, jpeg, or webp (default: png)

    Returns:
        bytes: The generated image data
    """
    import base64

    def api_call():
        return client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            output_format=output_format,
            n=1
        )

    response = call_api_with_backoff(
        api_call=api_call,
        resource_type="image_generation"
    )

    # Decode the base64 image data
    image_base64 = response.data[0].b64_json
    return base64.b64decode(image_base64)

def call_claude_api(
    client: Anthropic,
    messages: List[Dict[str, str]],
    system_prompt: str = None,
    model: str = AI_MODEL,
    max_tokens: int = MAX_OUTPUT_TOKENS
) -> Any:
    """
    Makes an API call to Claude with exponential backoff for retries.

    Args:
        client: The Anthropic client instance
        messages: List of message dictionaries (role and content)
        system_prompt: Optional system prompt
        model: The model to use (default: claude-opus-4-5-20251101)
        max_tokens: Maximum tokens for the response

    Returns:
        The API response
    """
    # Count tokens in the request (approximate)
    total_tokens = sum(num_tokens_from_string(msg["content"]) for msg in messages)
    if system_prompt:
        total_tokens += num_tokens_from_string(system_prompt)

    if total_tokens > MAX_TOKENS_PER_REQUEST:
        logging.warning(f"Request too large ({total_tokens} tokens). This may exceed limits.")

    # Prepare the API call
    def api_call():
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        return client.messages.create(**kwargs)

    return call_api_with_backoff(
        api_call=api_call,
        resource_type="completions"
    )

def call_claude_parse_with_backoff(
    client: Anthropic,
    messages: List[Dict[str, str]],
    response_model: Type[BaseModel],
    model: str = AI_MODEL,
    max_tokens: int = MAX_OUTPUT_TOKENS
) -> Any:
    """
    Makes a Claude API call and parses the response into a Pydantic model.

    Args:
        client: The Anthropic client instance
        messages: List of message dictionaries to send
        response_model: Pydantic model to parse the response into
        model: The model to use (default: claude-opus-4-5-20251101)
        max_tokens: Maximum tokens for the response

    Returns:
        An object with a structure similar to OpenAI's parse response
        for compatibility with existing code
    """
    # Extract system prompt from messages if present
    system_prompt = None
    claude_messages = []

    for msg in messages:
        if msg["role"] == "system":
            system_prompt = msg["content"]
        else:
            claude_messages.append(msg)

    # Get the JSON schema from the Pydantic model
    schema = response_model.model_json_schema()

    # Add instruction to return JSON matching the schema
    schema_instruction = (
        f"\n\nYou must respond with valid JSON that matches this schema:\n"
        f"```json\n{json.dumps(schema, indent=2)}\n```\n"
        f"Respond ONLY with the JSON, no additional text."
    )

    if system_prompt:
        system_prompt += schema_instruction
    else:
        system_prompt = schema_instruction

    # Count tokens in the request (approximate)
    total_tokens = sum(num_tokens_from_string(msg["content"]) for msg in claude_messages)
    total_tokens += num_tokens_from_string(system_prompt)

    if total_tokens > MAX_TOKENS_PER_REQUEST:
        logging.warning(f"Request too large ({total_tokens} tokens). This may exceed limits.")

    # Make the API call
    def api_call():
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=claude_messages
        )

    response = call_api_with_backoff(
        api_call=api_call,
        resource_type="completions"
    )

    # Extract the text content from Claude's response
    response_text = response.content[0].text

    # Clean up the response - remove markdown code blocks if present
    if response_text.startswith("```"):
        # Remove opening code block
        lines = response_text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Remove closing code block
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response_text = "\n".join(lines)

    # Parse the JSON response into the Pydantic model
    try:
        parsed_data = json.loads(response_text)
        parsed_model = response_model.model_validate(parsed_data)
    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse JSON response: {e}")
        logging.error(f"Response text: {response_text[:500]}...")
        raise
    except Exception as e:
        logging.error(f"Failed to validate response against model: {e}")
        raise

    # Create a response object that mimics OpenAI's structure for compatibility
    class ParsedMessage:
        def __init__(self, parsed):
            self.parsed = parsed

    class ParsedChoice:
        def __init__(self, parsed):
            self.message = ParsedMessage(parsed)

    class ParsedResponse:
        def __init__(self, parsed):
            self.choices = [ParsedChoice(parsed)]

    return ParsedResponse(parsed_model)

# Alias for backward compatibility
def call_openai_parse_with_backoff(
    client,
    messages: List[Dict[str, str]],
    response_model: Type[BaseModel],
    model: str = AI_MODEL
) -> Any:
    """
    Wrapper that routes to Claude API.
    Maintains backward compatibility with existing code that expects OpenAI-style interface.
    """
    # The client passed in is now an Anthropic client
    return call_claude_parse_with_backoff(
        client=client,
        messages=messages,
        response_model=response_model,
        model=model
    )

def get_content_collection_timeframe():
    """
    Determines the appropriate timeframe for content collection based on the current day.

    Returns:
        tuple: (start_datetime, end_datetime) - both timezone aware in configured timezone
    """
    # Get current time in configured timezone
    now = datetime.now(TIMEZONE)

    # Set end time to 6am today
    end_datetime = now.replace(hour=6, minute=0, second=0, microsecond=0)

    # Determine start date based on current day of the week
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    # If today is Saturday (5), Sunday (6), or Monday (0)
    if weekday in [0, 5, 6]:
        # Go back to Friday 6am (or previous Friday if it's already past 6am on Friday)
        days_to_friday = {
            0: 3,  # Monday -> go back 3 days to Friday
            5: 1,  # Saturday -> go back 1 day to Friday
            6: 2,  # Sunday -> go back 2 days to Friday
        }
        start_datetime = end_datetime - timedelta(days=days_to_friday[weekday])
    else:
        # For Tuesday through Friday, just go back 1 day (to 6am yesterday)
        start_datetime = end_datetime - timedelta(days=1)

    return start_datetime, end_datetime
