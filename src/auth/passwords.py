from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
import re

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
DUMMY = hasher.hash("dummy-password-never-used-for-login")

def username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.@+-]{2,127}", value):
        raise ValueError("Use 3-128 letters, digits or _.@+- for the username")
    return value

def password_hash(value):
    if not 15 <= len(value) <= 128:
        raise ValueError("Password must contain 15-128 characters")
    return hasher.hash(value)

def verify(value, encoded):
    try:
        return hasher.verify(encoded or DUMMY, value) and encoded is not None
    except (VerificationError, InvalidHashError):
        return False
