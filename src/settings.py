from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=('.env','/run/secrets/app_env'), env_prefix='JOBSEARCH_', extra='ignore')
    database_url: str = ''
    origin: str = 'http://localhost:3105'
    secure_cookies: bool = False
    session_hours: int = 8
    schedule_hours: int = 6
    max_response_bytes: int = 20_000_000

@lru_cache
def settings():
    return Settings()
