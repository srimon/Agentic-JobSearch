"""Time-based one-time passwords (RFC 6238 over RFC 4226 HOTP) and recovery codes, standard library only."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

ISSUER = 'Bagala'
DIGITS = 6
PERIOD = 30
WINDOW = 1  # accept one step either side of now for clock drift
RECOVERY_ALPHABET = '23456789abcdefghjkmnpqrstuvwxyz'  # no 0/o, 1/i/l
RECOVERY_COUNT = 10


def now():
    """Seconds since the epoch; a seam for tests."""
    return time.time()


def new_secret():
    """20 random bytes (160 bits, the RFC 4226 recommendation) as unpadded base32."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def secret_bytes(secret):
    secret = secret.strip().replace(' ', '').upper()
    return base64.b32decode(secret + '=' * (-len(secret) % 8))


def hotp(key, counter, digits=DIGITS, digest=hashlib.sha1):
    mac = hmac.new(key, struct.pack('>Q', counter), digest).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack('>I', mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** digits).zfill(digits)


def totp(secret, at=None, digits=DIGITS, period=PERIOD):
    return hotp(secret_bytes(secret), int(now() if at is None else at) // period, digits)


def normalize_code(code):
    return ''.join((code or '').split())


def is_totp_code(code):
    code = normalize_code(code)
    return len(code) == DIGITS and code.isascii() and code.isdigit()


def matching_step(secret, code, last_used_step=None, at=None):
    """The time step the code belongs to, or None. Every candidate is compared in constant time, and a step at or
    before the last accepted one is refused so an observed code cannot be replayed."""
    code = normalize_code(code)
    if not is_totp_code(code):
        return None
    key = secret_bytes(secret)
    current = int(now() if at is None else at) // PERIOD
    found = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(hotp(key, step), code) and found is None:
            found = step
    if found is None or (last_used_step is not None and found <= last_used_step):
        return None
    return found


def provisioning_uri(account, secret):
    return ('otpauth://totp/' + ISSUER + ':' + quote(account, safe='') + '?secret=' + secret +
            '&issuer=' + ISSUER + '&digits=' + str(DIGITS) + '&period=' + str(PERIOD))


def qr_svg(uri):
    """Inline SVG QR code rendered with segno (pure Python); None when the package is not installed."""
    try:
        import io
        import segno
    except ImportError:
        return None
    buffer = io.BytesIO()
    segno.make(uri, error='m', micro=False).save(buffer, kind='svg', scale=5, border=2, dark='#000', light='#fff',
                                                  xmldecl=False, svgns=True, svgclass=None, lineclass=None)
    return buffer.getvalue().decode()


def new_recovery_codes():
    """Ten codes of ten characters from a 31-letter alphabet (about 49 bits each), shown as xxxxx-xxxxx."""
    codes = []
    for _ in range(RECOVERY_COUNT):
        raw = ''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        codes.append(raw[:5] + '-' + raw[5:])
    return codes


def normalize_recovery(code):
    return ''.join(ch for ch in (code or '').lower() if ch not in ' -\t\n')


def recovery_hash(user_id, code):
    """Bound to the account so equal codes of two accounts never share a digest."""
    return hashlib.sha256((str(user_id) + ':' + normalize_recovery(code)).encode()).hexdigest()
