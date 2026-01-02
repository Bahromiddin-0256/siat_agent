"""Time utility functions."""
from datetime import datetime, time, date
from typing import Optional
import pytz

from app.config import settings


def get_timezone():
    """Get configured timezone."""
    return pytz.timezone(settings.timezone)


def now() -> datetime:
    """Get current datetime in configured timezone."""
    tz = get_timezone()
    return datetime.now(tz)


def today() -> date:
    """Get current date in configured timezone."""
    return now().date()


def format_time(t: time) -> str:
    """Format time in HH:MM format."""
    return t.strftime("%H:%M")


def format_date(d: date) -> str:
    """Format date in DD.MM.YYYY format."""
    return d.strftime("%d.%m.%Y")


def format_datetime(dt: datetime) -> str:
    """Format datetime in DD.MM.YYYY HH:MM format."""
    return dt.strftime("%d.%m.%Y %H:%M")


def parse_time(time_str: str) -> Optional[time]:
    """Parse time string in HH:MM format."""
    try:
        hour, minute = map(int, time_str.split(":"))
        return time(hour, minute)
    except (ValueError, AttributeError):
        return None


def get_weekday_name(weekday: int) -> str:
    """Get weekday name in Uzbek."""
    names = {
        0: "Dushanba",
        1: "Seshanba",
        2: "Chorshanba",
        3: "Payshanba",
        4: "Juma",
        5: "Shanba",
        6: "Yakshanba"
    }
    return names.get(weekday, "Noma'lum")
