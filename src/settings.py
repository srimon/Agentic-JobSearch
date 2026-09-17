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


def origin_of(address):
    """The scheme://host[:port] of a browser-facing address, which may carry a path.

    A product served at a short path (https://bagala.ai/jobsearch) posts with the Origin of the
    host it is on, so that is what an origin list has to hold."""
    text = (address or '').strip()
    scheme, separator, rest = text.partition('://')
    if not separator:
        return text.rstrip('/')
    return scheme + '://' + rest.split('/')[0]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=('.env','/run/secrets/app_env'), env_prefix='JOBSEARCH_', extra='ignore')
    database_url: str = ''
    # Connection pool of the API process only (src/db/store.py open_pool, opened by the FastAPI
    # lifespan). The worker, scheduler, mailer and scripts never open it. Each API copy holds at
    # most max_size connections, so three copies hold at most 18. A borrower that waits longer than
    # timeout, or arrives while max_waiting others wait (0 = unbounded), gets the same 503 as an
    # unreachable database; anyio runs sync routes on 40 threads, hence 40.
    database_pool_min_size: int = Field(default=1, ge=0)
    database_pool_max_size: int = Field(default=6, ge=1)
    database_pool_timeout_seconds: float = Field(default=5, gt=0)
    database_pool_max_waiting: int = Field(default=40, ge=0)
    database_pool_max_lifetime_seconds: float = Field(default=1800, gt=0)
    database_pool_max_idle_seconds: float = Field(default=300, gt=0)
    data_management_enabled: bool = False
    maintenance_mode: bool = False
    origin: str = 'http://localhost:3105'
    # Browser-facing address used in emailed links (verification, password reset) and in the
    # returns other products send here; defaults to origin. It may carry a path, because the
    # products are moving to short paths on one host: production is https://bagala.ai/jobsearch.
    public_origin: str = ''
    # The product-neutral account screen the hub serves on the bare domain (the hub's
    # docs/plans/account-screen.md). Emailed verification and reset links open its pages
    # (/verify?token=, /reset?token=) when the request arrived through the public edge, i.e. on
    # cookie_domain; the loopback name keeps this product's own landings (/?verify=, /?reset=)
    # because the screen is not served there. Empty keeps the landings everywhere.
    account_screen: str = 'https://bagala.ai/account'
    # Origins accepted by the CSRF check for state-changing requests; defaults to origin plus public_origin.
    allowed_origins: Annotated[list[str], NoDecode] = []
    # Hub origins allowed to read /api/workflow with credentials (CORS special case).
    hub_origins: Annotated[list[str], NoDecode] = ['http://localhost:3180']
    # Origins the library gateway may forward for state-changing requests (/api/hub/library-authorize).
    library_origins: Annotated[list[str], NoDecode] = ['http://localhost:3001','http://localhost:3011','http://localhost:8000','http://localhost:8010']
    # Reader questions a non-administrator may ask the Library per UTC day (/api/hub/library-authorize); 0 = unlimited.
    reader_daily_question_limit: int = Field(default=50, ge=0)
    # JSON objects of links the front end shows: public when the request host is on cookie_domain, local otherwise.
    # Job Prep and the Library are advertised at their short paths on the shared host; prep.bagala.ai and
    # library.bagala.ai still serve the same applications, so an existing link or bookmark keeps working.
    hub_links_local: dict[str, str] = {'hub':'http://localhost:3180/','library':'http://localhost:3001/reader','prep':'http://localhost:3188/'}
    hub_links_public: dict[str, str] = {'hub':'https://hub.bagala.ai/','library':'https://bagala.ai/library/reader','prep':'https://bagala.ai/jobprep/'}
    # Session cookie: '' keeps host-only cookies; 'bagala.ai' shares the cookie across *.bagala.ai hosts.
    cookie_domain: str = ''
    cookie_samesite: Literal['lax','strict','none'] = 'lax'
    # None resolves to True when public_origin is https; the Secure flag is still applied per request.
    secure_cookies: bool | None = None
    session_hours: int = 8
    # A signed-in account that is not an administrator is signed out after this many minutes
    # without an authenticated request, in every product that authenticates here (Job Search,
    # Job Prep, the Library). 0 switches the idle limit off; session_hours still applies.
    idle_minutes: int = Field(default=5, ge=0)
    signup_enabled: bool = False
    # A new account is a member: viewer alone cannot open Job Prep (it asks for member or above),
    # so self-service sign-ups could reach only Job Search and the Library (16 Sep 2026).
    signup_default_roles: Annotated[list[str], NoDecode] = ['member']
    # Account creation options (the hub's docs/plans/account-creation-options.md). Every switch is
    # off by default, so deploying the code changes nothing until the owner turns a stage on.
    # The phone-scan check: the sign-up form shows a QR code that a phone scans within
    # signup_scan_seconds to confirm a person with a handheld device is behind the sign-up.
    signup_scan_enabled: bool = False
    signup_scan_seconds: int = Field(default=120, ge=30, le=600)
    # The default second sign-in step for an account without an authenticator app: a six-digit
    # code sent to the verified e-mail address. Accounts with an authenticator keep using it.
    login_email_code: bool = False
    # Approving a sign-in from a phone that is already signed in: the two-step page draws a code
    # that lives login_scan_seconds (QR flow 2 of the plan). No SMS and no phone numbers (the
    # owner, 17 Sep 2026): the phone columns of the sign-up record stay unused.
    login_scan_approval: bool = False
    login_scan_seconds: int = Field(default=120, ge=30, le=600)
    # Consent regimes are read from the visitor's location. A US visitor whose region is unknown
    # (the location headers are off at the edge) is treated like a Californian while this is on.
    consent_strict_unknown_region: bool = True
    # Sign-in context rows are kept this long (a year: the owner's analytics keep country, city and
    # device); sign-up rows live as long as the account. The network address in any row is blanked
    # after context_address_retention_months by scripts/context_purge.py, the rest of the row kept.
    context_signin_retention_days: int = Field(default=365, ge=1, le=3650)
    context_address_retention_months: int = Field(default=12, ge=1, le=120)
    # API keys (stage 2 of the hub's docs/plans/api-gateway-and-mcp.md; src/auth/api_keys.py). Off by
    # default, so the image alone changes nothing until JOBSEARCH_API_KEYS_ENABLED=true is rolled through
    # the ConfigMap; off again is the rollback (keys refused, everything else as before).
    api_keys_enabled: bool = False
    # Calls per key per UTC day: the ceiling a key may be given at creation, and its default. 0 = unlimited.
    api_key_daily_quota: int = Field(default=1000, ge=0)
    # Active (unrevoked) keys one account may hold.
    api_keys_per_account: int = Field(default=10, ge=1, le=100)
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
    # Administrator console (src/api/admin_console.py). The warehouse identity is read-only and its
    # password is a mounted file, never an environment value; without the file the console's
    # warehouse panels say so instead of failing. Prometheus is the ExternalName service in this
    # namespace that the API already has egress to.
    admin_clickhouse_url: str = 'http://clickhouse.hub-data.svc.cluster.local:8123'
    admin_clickhouse_user: str = 'hub_admin_console'
    admin_clickhouse_password_file: str = '/run/secrets/admin-console/clickhouse-password'
    admin_prometheus_url: str = 'http://prometheus:9090'

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
        self.account_screen = self.account_screen.strip().rstrip('/')
        if not self.allowed_origins:
            # An Origin header is scheme://host[:port] and never carries a path, so a public
            # address on a short path (https://bagala.ai/jobsearch) contributes its origin.
            public = origin_of(self.public_origin)
            self.allowed_origins = [self.origin] + ([public] if public != self.origin else [])
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
