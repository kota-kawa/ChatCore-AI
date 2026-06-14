import base64
import hashlib
import hmac
import secrets
from typing import Optional

_CODE_LOWER_BOUND = 100000
_CODE_RANGE = 900000
_PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
_DEFAULT_PBKDF2_ITERATIONS = 390000
_DEFAULT_SALT_BYTES = 16


# 日本語: ログインや確認用の6桁の数値検証コードを生成します。
# English: Generate a six-digit numeric verification code for login or confirmation.
def generate_verification_code() -> str:
    # 日本語: 暗号論的に安全な乱数生成器を用いて 100000 から 999999 までの6桁の数値を生成します。
    # English: Generate a six-digit number between 100000 and 999999 using a cryptographically secure random number generator.
    return str(secrets.randbelow(_CODE_RANGE) + _CODE_LOWER_BOUND)


# 日本語: タイミング攻撃を防ぐため、文字列をハッシュ化し定数時間で比較します。
# English: Compare two strings in constant time using their hashed values to prevent timing attacks.
def constant_time_compare(left: str, right: str) -> bool:
    # 日本語: 入力長差による比較時間の偏りを減らすため、先に同一長のダイジェストへ変換して比較します。
    # English: Hash both inputs first to reduce timing leakage from raw string length differences.
    left_digest = hashlib.sha256(str(left).encode("utf-8")).digest()
    right_digest = hashlib.sha256(str(right).encode("utf-8")).digest()
    return hmac.compare_digest(left_digest, right_digest)


# 日本語: PBKDF2アルゴリズムを用いてパスワードをハッシュ化し、保存用の文字列形式を生成します。
# English: Hash a password using the PBKDF2 algorithm and generate a formatted string for storage.
def hash_password(
    password: str,
    *,
    iterations: int = _DEFAULT_PBKDF2_ITERATIONS,
    salt: Optional[bytes] = None,
) -> str:
    # 日本語: パラメータの妥当性をチェックし、PBKDF2 でハッシュ化し、scheme$iterations$salt$digest 形式で保存します。
    # English: Validate parameters, hash with PBKDF2, and encode as scheme$iterations$salt$digest.
    if not isinstance(password, str) or password == "":
        raise ValueError("password must be a non-empty string")
    if iterations <= 0:
        raise ValueError("iterations must be a positive integer")
    salt_bytes = salt if salt is not None else secrets.token_bytes(_DEFAULT_SALT_BYTES)
    if not salt_bytes:
        raise ValueError("salt must not be empty")

    password_bytes = password.encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", password_bytes, salt_bytes, iterations)
    salt_b64 = base64.b64encode(salt_bytes).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"{_PASSWORD_HASH_SCHEME}${iterations}${salt_b64}${digest_b64}"


# 日本語: 保存されているハッシュ文字列を解析し、入力されたパスワードと一致するか定数時間で検証します。
# English: Parse a stored password hash and verify it against the input password using constant-time comparison.
def verify_password(password: str, password_hash: str) -> bool:
    # 日本語: 保存形式を厳密に検証したうえで同条件で再計算し、定数時間比較します。
    # English: Validate stored hash format, recompute with same params, then compare in constant time.
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False

    parts = password_hash.split("$")
    if len(parts) != 4:
        return False

    scheme, iterations_raw, salt_b64, expected_digest_b64 = parts
    if scheme != _PASSWORD_HASH_SCHEME:
        return False

    try:
        iterations = int(iterations_raw)
        if iterations <= 0:
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"), validate=True)
        expected_digest = base64.b64decode(
            expected_digest_b64.encode("ascii"), validate=True
        )
    except (ValueError, TypeError):
        return False

    if not salt or not expected_digest:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(actual_digest, expected_digest)
