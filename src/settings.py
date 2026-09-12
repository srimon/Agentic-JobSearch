from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=('.env','/run/secrets/app_env'), env_prefix='JOBSEARCH_', extra='ignore')
    database_url: str = ''
    origin: str = 'http://localhost:3105'
    secure_cookies: bool = False
    session_hours: int = 8
    schedule_hours: int = 24
    schedule_hour: int = Field(default=8, ge=0, le=23)
    schedule_timezone: str = 'America/Los_Angeles'
    worker_lease_seconds: int = Field(default=120, ge=10, le=600)
    worker_heartbeat_seconds: int = Field(default=20, ge=1)
    worker_max_run_seconds: int = Field(default=900, ge=30, le=7200)
    worker_shutdown_seconds: int = Field(default=60, ge=1, le=300)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode='after')
    def validate_worker_timing(self):
        if self.worker_heartbeat_seconds * 3 > self.worker_lease_seconds:
            raise ValueError('Worker heartbeat must be at most one third of lease duration')
        if self.worker_max_run_seconds <= self.worker_lease_seconds:
            raise ValueError('Worker run budget must exceed lease duration')
        return self

    max_response_bytes: int = 20_000_000

@lru_cache
def settings():
    return Settings()
