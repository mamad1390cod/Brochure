"""
Security utilities for Bot-File-School.
Handles password hashing, verification, and rate limiting.
"""

import hashlib
import secrets
import time
from typing import Dict, Tuple

PASSWORD_HASH_ITERATIONS = 600_000
_PASSWORD_HASH_PREFIX = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random salt."""
    password = (password or "").strip().casefold()
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    ).hex()
    return f"{_PASSWORD_HASH_PREFIX}${PASSWORD_HASH_ITERATIONS}${salt.hex()}${hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash.

    Admin panel passwords are CASE-INSENSITIVE: 'parham11', 'PARHAM11'
    and 'Parham11' are all accepted. Comparison runs on the casefolded
    input; legacy hashes of already-lowercase passwords still match.
    Only admin login uses this - usernames/names/files are unaffected.
    """
    password = (password or "").strip().casefold()
    if stored_hash.startswith(f"{_PASSWORD_HASH_PREFIX}$"):
        try:
            _, raw_iterations, raw_salt, expected_hash = stored_hash.split("$", 3)
            iterations = int(raw_iterations)
            salt = bytes.fromhex(raw_salt)
            if not 1 <= iterations <= 1_000_000:
                return False
        except (ValueError, TypeError):
            return False
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        ).hex()
        return secrets.compare_digest(actual_hash, expected_hash)

    # Accept existing salted SHA-256 hashes; successful logins can upgrade them.
    if "$" not in stored_hash:
        return False
    salt, expected_hash = stored_hash.split("$", 1)
    actual_hash = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return secrets.compare_digest(actual_hash, expected_hash)


def password_hash_needs_upgrade(stored_hash: str) -> bool:
    """Return whether a stored password uses the legacy fast hash format."""
    return not stored_hash.startswith(f"{_PASSWORD_HASH_PREFIX}$")


class LoginRateLimiter:
    """Simple in-memory rate limiter for login attempts."""

    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 15):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_minutes * 60
        # user_id -> (attempt_count, first_attempt_time)
        self._attempts: Dict[int, Tuple[int, float]] = {}

    def is_locked(self, user_id: int) -> bool:
        """Check if a user is currently locked out."""
        if user_id not in self._attempts:
            return False
        count, first_time = self._attempts[user_id]
        if count >= self.max_attempts:
            if time.time() - first_time < self.lockout_seconds:
                return True
            else:
                # Lockout expired, reset
                del self._attempts[user_id]
                return False
        return False

    def record_attempt(self, user_id: int) -> None:
        """Record a failed login attempt."""
        if user_id in self._attempts:
            count, first_time = self._attempts[user_id]
            self._attempts[user_id] = (count + 1, first_time)
        else:
            self._attempts[user_id] = (1, time.time())

    def reset(self, user_id: int) -> None:
        """Reset attempts after successful login."""
        self._attempts.pop(user_id, None)

    def get_remaining_time(self, user_id: int) -> int:
        """Get remaining lockout time in seconds."""
        if user_id not in self._attempts:
            return 0
        count, first_time = self._attempts[user_id]
        if count >= self.max_attempts:
            remaining = self.lockout_seconds - (time.time() - first_time)
            return max(0, int(remaining))
        return 0


class AdminSessionManager:
    """In-memory manager of authenticated admin sessions.

    Admins must verify their password once per bot run before the
    admin panel becomes available to them.
    A session expires after ADMIN_SESSION_TIMEOUT (default 5 minutes) of
    inactivity, but is refreshed (sliding) on every authenticated action.
    A valid session spares the admin from re-entering the password on /start.
    """

    def __init__(self, timeout_seconds: int = 300):
        self.timeout_seconds = timeout_seconds
        self._authenticated: Dict[int, float] = {}  # user_id -> last_active_ts

    def login(self, user_id: int) -> None:
        self._authenticated[user_id] = time.time()

    def logout(self, user_id: int) -> None:
        self._authenticated.pop(user_id, None)

    def refresh(self, user_id: int) -> None:
        if user_id in self._authenticated:
            self._authenticated[user_id] = time.time()

    def is_authenticated(self, user_id: int) -> bool:
        if user_id not in self._authenticated:
            return False
        if time.time() - self._authenticated[user_id] > self.timeout_seconds:
            # 5 min of inactivity -> panel session expired
            del self._authenticated[user_id]
            return False
        return True


# Global rate limiter instance
rate_limiter = LoginRateLimiter()

# Global authenticated-admin session manager
admin_sessions = AdminSessionManager()
