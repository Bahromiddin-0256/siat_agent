"""Input validators."""
import re
from typing import Optional


def validate_phone_number(phone: str) -> tuple[bool, Optional[str]]:
    """
    Validate and normalize phone number.
    Returns (is_valid, normalized_phone).
    """
    
    # Remove spaces and special characters
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Check if it contains only digits and optional leading +
    if not re.match(r'^\+?\d+$', phone):
        return False, None
    
    # Remove leading + for processing
    if phone.startswith('+'):
        phone = phone[1:]
    
    # Handle Uzbekistan numbers
    if phone.startswith('998'):
        # Already has country code
        normalized = f"+{phone}"
    elif len(phone) == 9:
        # Local number without country code
        normalized = f"+998{phone}"
    elif len(phone) == 12 and phone.startswith('998'):
        # Has country code
        normalized = f"+{phone}"
    else:
        # Try to add +998 prefix
        normalized = f"+998{phone}"
    
    # Validate length (should be +998 + 9 digits = 13 characters)
    if len(normalized) == 13 and normalized.startswith('+998'):
        return True, normalized
    
    return False, None


def validate_name(name: str) -> tuple[bool, str]:
    """
    Validate patient/doctor name.
    Returns (is_valid, error_message).
    """
    
    name = name.strip()
    
    if len(name) < 3:
        return False, "Ism juda qisqa (kamida 3 harf bo'lishi kerak)"
    
    if len(name) > 100:
        return False, "Ism juda uzun (100 harfdan oshmasligi kerak)"
    
    # Check if contains at least some letters
    if not re.search(r'[a-zA-Zа-яА-ЯёЁўЎғҒқҚҳҲ]', name):
        return False, "Ism harflarni o'z ichiga olishi kerak"
    
    return True, ""


def validate_telegram_id(telegram_id_str: str) -> tuple[bool, Optional[int]]:
    """
    Validate Telegram ID.
    Returns (is_valid, telegram_id).
    """
    
    try:
        telegram_id = int(telegram_id_str)
        
        # Telegram IDs are positive integers
        if telegram_id < 0:
            return False, None
        
        # 0 means "not set" or "skip"
        if telegram_id == 0:
            return True, None
        
        # Telegram IDs are usually at least 5 digits
        if telegram_id < 10000:
            return False, None
        
        return True, telegram_id
    
    except ValueError:
        return False, None


def sanitize_text(text: str) -> str:
    """
    Sanitize user input text.
    Remove potentially harmful characters.
    """
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove excessive whitespace
    text = ' '.join(text.split())
    
    return text.strip()
