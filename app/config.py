"""Configuration settings for the dental clinic bot."""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import time


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Telegram Bot
    bot_token: str
    admin_ids: str = "123456789"
    
    # Database
    database_url: str
    
    # Application
    timezone: str = "Asia/Tashkent"
    default_duration: int = 20
    clinic_open: str = "09:00"
    clinic_close: str = "18:00"
    daily_reset_time: str = "08:00"
    max_queue_size: int = 50
    notification_threshold: int = 3
    link_expiry_hours: int = 24
    lunch_break_start: str = "13:00"
    lunch_break_end: str = "14:00"
    
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False
    
    # Redis (optional)
    redis_url: str = "redis://localhost:6379/0"
    
    @property
    def admin_id_list(self) -> List[int]:
        """Convert admin IDs string to list of integers."""
        return [int(id.strip()) for id in self.admin_ids.split(",") if id.strip()]
    
    def get_clinic_open_time(self) -> time:
        """Parse clinic opening time."""
        hour, minute = map(int, self.clinic_open.split(":"))
        return time(hour, minute)
    
    def get_clinic_close_time(self) -> time:
        """Parse clinic closing time."""
        hour, minute = map(int, self.clinic_close.split(":"))
        return time(hour, minute)
    
    def get_lunch_break_start(self) -> time:
        """Parse lunch break start time."""
        hour, minute = map(int, self.lunch_break_start.split(":"))
        return time(hour, minute)
    
    def get_lunch_break_end(self) -> time:
        """Parse lunch break end time."""
        hour, minute = map(int, self.lunch_break_end.split(":"))
        return time(hour, minute)


# Global settings instance
settings = Settings()
