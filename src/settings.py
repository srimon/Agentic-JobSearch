from functools import lru_cache
from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROLES = ('viewer', 'member', 'operator', 'administrator')


def split_list(value):
    """Comma-separated environment values become lists; blanks and trailing slashes are dropped."""
    if isinstance(value, str):
        return [item.strip().rstrip('/') for item in value.split(',') if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=('.env','/run/secrets/app_env'), env_prefix='JOBSEARCH_', extra='ignore')
    database_url: str = ''
    data_management_enabled: bool = False
    maintenance_mode: bool = False
    origin: str = 'http://localhost:3105'
    # Browser-facing origin used in emailed links; defaults to origin. Production: https://jobs.bagala.ai
    public_origin: str = ''
    # Origins accepted by the CSRF check for state-changing requests; defaults to origin plus public_origin.
    allowed_origins: Annotated[list[str], NoDecode] = []
    # Hub origins allowed to read /api/workflow with credentials (CORS special case).
    hub_origins: Annotated[list[str], NoDecode] = ['http://localhost:3180']
    # Origins the library gateway may forward for state-changing requests (/api/hub/library-authorize).
    library_origins: Annotated[list[str], NoDecode] = ['http://localhost:3001','http://localhost:3011','http://localhost:8000','http://localhost:8010']
    # JSON objects of links the front end shows: public when the request host is on cookie_domain, local otherwise.
    hub_links_local: dict[str, str] = {'hub':'http://localhost:3180/','library':'http://localhost:3001/reader','prep':'http://localhost:3188/'}
    hub_links_public: dict[str, str] = {'hub':'https://hub.bagala.ai/','library':'https://library.bagala.ai/reader','prep':'https://prep.bagala.ai/'}
    # Session cookie: '' keeps host-only cookies; 'bagala.ai' shares the cookie across *.bagala.ai hosts.
    cookie_domain: str = ''
    cookie_samesite: Literal['lax','strict','none'] = 'lax'
    # None resolves to True when public_origin is https; the Secure flag is still applied per request.
    secure_cookies: bool | None = None
    session_hours: int = 8
    signup_enabled: bool = False
    signup_default_roles: Annotated[list[str], NoDecode] = ['viewer']
    mail_transport: Literal['log','resend'] = 'log'
    mail_from: str = 'Bagala <no-reply@bagala.ai>'
    resend_api_key_file: str = '/run/secrets/resend/api.key'
    report_recipient: str = 'sean.chopparapu@gmail.com'
    # Where footer enquiries (POST /api/enquiries) are mailed; empty falls back to report_recipient.
    enquiry_recipient: str = ''
    owner_username: str = 'admin'
    schedule_hours: int = 24
    schedule_hour: int = Field(default=8, ge=0, le=23)
    schedule_timezone: str = 'America/Los_Angeles'
    worker_lease_seconds: int = Field(default=120, ge=10, le=600)
    worker_heartbeat_seconds: int = Field(default=20, ge=1)
    worker_max_run_seconds: int = Field(default=900, ge=30, le=7200)
    worker_shutdown_seconds: int = Field(default=60, ge=1, le=300)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)

    @field_validator('allowed_origins','hub_origins','library_origins','signup_default_roles', mode='before')
    @classmethod
    def parse_lists(cls, value):
        return split_list(value)

    @field_validator('cookie_samesite', mode='before')
    @classmethod
    def lower_samesite(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode='after')
    def validate_worker_timing(self):
        if self.worker_heartbeat_seconds * 3 > self.worker_lease_seconds:
            raise ValueError('Worker heartbeat must be at most one third of lease duration')
        if self.worker_max_run_seconds <= self.worker_lease_seconds:
            raise ValueError('Worker run budget must exceed lease duration')
        return self

    @model_validator(mode='after')
    def resolve_public_edge(self):
        self.origin = self.origin.strip().rstrip('/')
        self.public_origin = (self.public_origin.strip().rstrip('/')) or self.origin
        if not self.allowed_origins:
            self.allowed_origins = [self.origin] + ([self.public_origin] if self.public_origin != self.origin else [])
        if self.secure_cookies is None:
            self.secure_cookies = self.public_origin.startswith('https://')
        self.cookie_domain = self.cookie_domain.strip().lower().lstrip('.')
        if not self.signup_default_roles or set(self.signup_default_roles) - set(ROLES):
            raise ValueError('signup_default_roles must be a non-empty subset of ' + ', '.join(ROLES))
        return self

    max_response_bytes: int = 20_000_000

@lru_cache
def settings():
    return Settings()
