import hashlib
import hmac
import secrets

_CODE_LOWER_BOUND = 100000
_CODE_RANGE = 900000


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
