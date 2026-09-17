"""What is known about the visitor behind an account request, and where it is kept.

The public edge names the visitor's address in X-Forwarded-For and, from Cloudflare's headers,
their location in X-Visitor-* (platform/gateway/public-edge.conf in the hub); the Job Search
gateway passes both on. Country is on every request through Cloudflare; city, region, postal
code, time zone and coordinates arrive only once the zone's "Add visitor location headers"
managed transform is on, and are empty until then. A loopback caller can send any of these, and
a loopback caller is an operator.

A context row is personal data: it is keyed to the account, deleted with it (ON DELETE CASCADE),
read by administrators only, and nothing in it is ever logged or put in an audit record. The
address is kept as sent, for abuse investigation and analytics; the edge statistics in
ClickHouse keep only a hashed form (the hub's scripts/edge_analytics.py).
"""
import ipaddress
import re
from src.settings import settings

# Header -> column. The edge sets every one of these from the CF-* header of the same meaning.
LOCATION_HEADERS = {'x-visitor-country': 'country', 'x-visitor-continent': 'continent', 'x-visitor-region': 'region',
                    'x-visitor-region-code': 'region_code', 'x-visitor-city': 'city', 'x-visitor-postal-code': 'postal_code',
                    'x-visitor-timezone': 'timezone'}
COORDINATES = {'x-visitor-latitude': 'latitude', 'x-visitor-longitude': 'longitude'}
TEXT_LIMIT = {'country': 8, 'continent': 8, 'region': 120, 'region_code': 16, 'city': 120, 'postal_code': 32, 'timezone': 64,
              'user_agent': 512, 'accept_language': 128, 'referrer': 512, 'address': 200, 'language': 32, 'client_timezone': 64}
DEVICE_CLASSES = ('phone', 'tablet', 'desktop', 'bot', 'unknown')
BOT = re.compile(r'bot|crawl|spider|slurp|curl/|wget/|python-requests|python-urllib|httpx/|go-http-client|okhttp|headless', re.I)
PHONE = re.compile(r'iPhone|iPod|Windows Phone|Mobile', re.I)
TABLET = re.compile(r'iPad|Tablet|Kindle|Silk', re.I)
EU = frozenset('AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE'.split())
# EEA members outside the EU apply the GDPR too.
EEA = EU | frozenset('IS LI NO'.split())


def clip(value, limit):
    text = ' '.join((value or '').split())
    return text[:limit] if text else None


def first_forwarded(request):
    """The visitor's address: the first X-Forwarded-For hop (the edge writes exactly one, from
    Cloudflare), else the connecting address. None when neither parses as an address."""
    raw = request.headers.get('x-forwarded-for', '').split(',')[0].strip()
    if not raw and request.client:
        raw = request.client.host or ''
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def coordinate(value):
    try:
        number = float((value or '').strip())
    except ValueError:
        return None
    return number if -180 <= number <= 180 else None


def device_class(user_agent):
    if not user_agent:
        return 'unknown'
    if BOT.search(user_agent):
        return 'bot'
    if TABLET.search(user_agent) or ('Android' in user_agent and 'Mobile' not in user_agent):
        return 'tablet'
    if PHONE.search(user_agent) or 'Android' in user_agent:
        return 'phone'
    return 'desktop'


def operating_system(user_agent):
    ua = user_agent or ''
    for needle, name in (('iPhone', 'iOS'), ('iPad', 'iPadOS'), ('Android', 'Android'), ('Windows', 'Windows'),
                         ('CrOS', 'ChromeOS'), ('Mac OS X', 'macOS'), ('Linux', 'Linux')):
        if needle in ua:
            return name
    return None


def browser(user_agent):
    ua = user_agent or ''
    for needle, name in (('Edg/', 'Edge'), ('SamsungBrowser', 'Samsung Internet'), ('OPR/', 'Opera'), ('Firefox/', 'Firefox'),
                         ('CriOS/', 'Chrome'), ('Chrome/', 'Chrome'), ('Safari/', 'Safari')):
        if needle in ua:
            return name
    return None


def visitor(request):
    """The request's context as column values: address, Cloudflare location, agent and its
    classes, language, referrer, the address the visitor used and whether Cloudflare's
    challenge cookie came along (present only after a human check was passed)."""
    agent = clip(request.headers.get('user-agent'), TEXT_LIMIT['user_agent'])
    host = request.headers.get('x-forwarded-host', '').split(',')[0].strip() or request.headers.get('host', '')
    prefix = request.headers.get('x-forwarded-prefix', '').split(',')[0].strip().rstrip('/')
    row = {'ip': first_forwarded(request), 'user_agent': agent, 'device_class': device_class(agent),
           'os': operating_system(agent), 'browser': browser(agent),
           'accept_language': clip(request.headers.get('accept-language'), TEXT_LIMIT['accept_language']),
           'referrer': clip(request.headers.get('referer'), TEXT_LIMIT['referrer']),
           'address': clip(host.lower() + prefix, TEXT_LIMIT['address']),
           'challenge_cookie': 'cf_clearance' in request.cookies}
    for header, column in LOCATION_HEADERS.items():
        row[column] = clip(request.headers.get(header), TEXT_LIMIT[column])
    for header, column in COORDINATES.items():
        row[column] = coordinate(request.headers.get(header))
    return row


def regime(country, region_code):
    """Which consent regime the visitor's location puts them under: EU/EEA and UK visitors and
    Californians must opt in; everyone else is opted in by default and told so. A US visitor
    whose region is unknown counts as a Californian while consent_strict_unknown_region is on."""
    country = (country or '').upper()
    if country in EEA:
        return 'eu'
    if country == 'GB':
        return 'uk'
    if country == 'US':
        code = (region_code or '').upper()
        if code == 'CA' or (not code and settings().consent_strict_unknown_region):
            return 'california'
    return 'other'


CLIENT_COLUMNS = ('screen_width', 'screen_height', 'pixel_ratio', 'touch_points', 'language', 'client_timezone')
COLUMNS = ('ip', 'country', 'continent', 'region', 'region_code', 'city', 'postal_code', 'timezone', 'latitude', 'longitude',
           'user_agent', 'device_class', 'os', 'browser', 'accept_language', 'referrer', 'address', 'challenge_cookie',
           'screen_width', 'screen_height', 'pixel_ratio', 'touch_points', 'language', 'client_timezone',
           'scan_seconds', 'same_network', 'phone_e164', 'phone_verified_at')


def record(conn, source, values, user_id=None, attempt_id=None):
    """One account_context row; returns its id."""
    row = {column: values.get(column) for column in COLUMNS}
    row['device_class'] = row['device_class'] if row['device_class'] in DEVICE_CLASSES else 'unknown'
    names = ['user_id', 'attempt_id', 'source'] + list(COLUMNS)
    params = [user_id, attempt_id, source] + [row[column] for column in COLUMNS]
    return conn.execute('INSERT INTO jobsearch.account_context(' + ','.join(names) + ') VALUES(' + ','.join(['%s'] * len(names)) + ') RETURNING id',
                        params).fetchone()['id']


def prune(conn):
    """Sign-in rows older than the retention window. Called from the sign-in transaction with
    SKIP LOCKED, like the other housekeeping in src/auth/local.py."""
    conn.execute("""DELETE FROM jobsearch.account_context WHERE id IN
      (SELECT id FROM jobsearch.account_context WHERE source='signin' AND recorded_at < now()-(%s * interval '1 day') FOR UPDATE SKIP LOCKED)""",
                 (settings().context_signin_retention_days,))
