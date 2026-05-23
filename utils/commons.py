import json
import random
import re
import string
from typing import Dict

from django.conf import settings
from rest_framework import serializers
from rest_framework.exceptions import APIException

SUCCESS_RESPONSE_DATA = json.loads('{"detail": "success"}')
PHONE_NUMBER_REGEX = "^(01)([0-9]{9})$"
USER_NAME_REGEX = "^[가-힣]{2,7}$"
PASSWORD_REGEX = (
    r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[@$!%*#?&])[A-Za-z\d@$!%*#?&]{8,20}$"
)


def is_test_env():
    return settings.ENV == "test"


def is_prod_env():
    return settings.ENV == "prod"


def get_random_password():
    result = ""
    for _ in range(5):
        result += random.choice(string.ascii_lowercase)
    for _ in range(5):
        result += random.choice(string.ascii_uppercase)
    for _ in range(5):
        result += random.choice(string.digits)
    for _ in range(5):
        result += random.choice("@$!%*#?&")
    return result


# refer to
# https://youtu.be/H6tWONXQi5w?si=c0LT3atL98h4CkcG
# https://github.com/DenverCoder1/github-readme-youtube-cards/blob/01ae3d84030fea9bd5fb59429a4dd894c6761855/action.py#L52
# https://github.com/bergercookie/taskw-ng/blob/21bc796954195bbece64c13cd69a14b9eda76d52/taskw_ng/fields/duration.py#L43
def parse_iso8601_duration(iso_duration: str) -> Dict[str, int]:
    """
    Parse an ISO 8601 duration string from YouTube (e.g., PT1H30M15S) into a dictionary.
    
    Args:
        iso_duration: ISO 8601 formatted duration string (e.g., PT1H30M15S)
        
    Returns:
        Dictionary containing days, hours, minutes, and seconds
    
    Examples:
        >>> parse_iso8601_duration("PT5M30S")
        {'days': 0, 'hours': 0, 'minutes': 5, 'seconds': 30}
        >>> parse_iso8601_duration("PT1H30M15S")
        {'days': 0, 'hours': 1, 'minutes': 30, 'seconds': 15}
        >>> parse_iso8601_duration("P1DT2H30M")
        {'days': 1, 'hours': 2, 'minutes': 30, 'seconds': 0}
    """
    # Handle empty or invalid input
    if not iso_duration or not isinstance(iso_duration, str):
        return {'days': 0, 'hours': 0, 'minutes': 0, 'seconds': 0}
        
    # Default values
    duration_dict = {'days': 0, 'hours': 0, 'minutes': 0, 'seconds': 0}
    
    # Match the duration pattern
    # Handles patterns like PT1H30M15S (1 hour, 30 minutes, 15 seconds)
    # or P1DT2H30M (1 day, 2 hours, 30 minutes)
    day_match = re.search(r'(\d+)D', iso_duration)
    hour_match = re.search(r'(\d+)H', iso_duration)
    minute_match = re.search(r'(\d+)M', iso_duration)
    second_match = re.search(r'(\d+)S', iso_duration)
    
    # Extract the values
    if day_match:
        duration_dict['days'] = int(day_match.group(1))
    if hour_match:
        duration_dict['hours'] = int(hour_match.group(1))
    if minute_match:
        duration_dict['minutes'] = int(minute_match.group(1))
    if second_match:
        duration_dict['seconds'] = int(second_match.group(1))
    
    return duration_dict


def format_duration(duration_dict: Dict[str, int], format_type: str = 'short') -> str:
    """
    Format a duration dictionary into a human-readable string.
    
    Args:
        duration_dict: Dictionary containing days, hours, minutes, and seconds
        format_type: Type of format to use (short, medium, or long)
        
    Returns:
        Human-readable duration string
        
    Examples:
        >>> format_duration({'days': 0, 'hours': 1, 'minutes': 30, 'seconds': 15}, 'short')
        '1:30:15'
        >>> format_duration({'days': 0, 'hours': 0, 'minutes': 5, 'seconds': 30}, 'short')
        '5:30'
        >>> format_duration({'days': 1, 'hours': 2, 'minutes': 30, 'seconds': 15}, 'medium')
        '1d 2h 30m 15s'
        >>> format_duration({'days': 0, 'hours': 1, 'minutes': 30, 'seconds': 15}, 'long')
        '1 hour 30 minutes 15 seconds'
    """
    days = duration_dict.get('days', 0)
    hours = duration_dict.get('hours', 0)
    minutes = duration_dict.get('minutes', 0)
    seconds = duration_dict.get('seconds', 0)
    
    if format_type == 'short':
        # Format as 5:30 or 1:30:15
        if days > 0:
            total_hours = days * 24 + hours
            return f"{total_hours}:{minutes:02d}:{seconds:02d}"
        elif hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
    
    elif format_type == 'medium':
        # Format as 1d 2h 30m 15s
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0:
            parts.append(f"{seconds}s")
        # Return at least seconds if everything is 0
        return " ".join(parts) if parts else "0s"
    
    elif format_type == 'long':
        # Format as 1 hour 30 minutes 15 seconds
        parts = []
        if days > 0:
            parts.append(f"{days} {'day' if days == 1 else 'days'}")
        if hours > 0:
            parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
        if minutes > 0:
            parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        if seconds > 0:
            parts.append(f"{seconds} {'second' if seconds == 1 else 'seconds'}")
        # Return at least seconds if everything is 0
        return " ".join(parts) if parts else "0 seconds"
    
    # If unknown format type, use short format
    return format_duration(duration_dict, 'short')


def format_iso8601_duration(iso_duration: str, format_type: str = 'short') -> str:
    """
    Parse an ISO 8601 duration string and format it into a human-readable string.
    
    Args:
        iso_duration: ISO 8601 formatted duration string (e.g., PT1H30M15S)
        format_type: Type of format to use (short, medium, or long)
        
    Returns:
        Human-readable duration string
        
    Examples:
        >>> format_iso8601_duration("PT1H30M15S", 'short')
        '1:30:15'
        >>> format_iso8601_duration("PT5M30S", 'short')
        '5:30'
        >>> format_iso8601_duration("P1DT2H30M15S", 'medium')
        '1d 2h 30m 15s'
    """
    duration_dict = parse_iso8601_duration(iso_duration)
    return format_duration(duration_dict, format_type)


def duration_to_seconds(duration_dict: Dict[str, int]) -> int:
    """
    Convert a duration dictionary to total seconds.
    
    Args:
        duration_dict: Dictionary containing days, hours, minutes, and seconds
        
    Returns:
        Total seconds
    """
    days = duration_dict.get('days', 0)
    hours = duration_dict.get('hours', 0)
    minutes = duration_dict.get('minutes', 0)
    seconds = duration_dict.get('seconds', 0)
    
    total_seconds = (
        days * 24 * 60 * 60 +
        hours * 60 * 60 +
        minutes * 60 +
        seconds
    )
    
    return total_seconds


def iso8601_duration_to_seconds(iso_duration: str) -> int:
    """
    Convert an ISO 8601 duration string to total seconds.
    
    Args:
        iso_duration: ISO 8601 formatted duration string (e.g., PT1H30M15S)
        
    Returns:
        Total seconds
    """
    duration_dict = parse_iso8601_duration(iso_duration)
    return duration_to_seconds(duration_dict)


class NeedSwaggerDescription(Exception):
    pass


class CustomAPIException(APIException):
    swagger_description = None

    def __init__(self):
        if not self.swagger_description:
            raise NeedSwaggerDescription(
                "need to declare swagger_description in CustomAPIException"
            )
        super().__init__()


class EmptySerializer(serializers.Serializer):
    pass
