import unittest

from services.security import (
    constant_time_compare,
    generate_verification_code,
    hash_password,
    verify_password,
)


# パスワードハッシュ化や照合、認証コード生成、タイミング攻撃防止用比較処理などのセキュリティ機能ユーティリティを検証するテストクラス。
# Test case class to verify the functionality and specifications of security utility functions.
class SecurityUtilsTestCase(unittest.TestCase):
    # 生成された確認コード（ワンタイムコード等）が数字6桁であり、正常な範囲に収まっていることを検証します。
    # Verify that the generated verification code is six digits and in the valid numeric range.
    def test_generate_verification_code_is_six_digits(self):
        # 複数回繰り返して生成されたコードが全て6桁の整数であることを検証
        # Verify that all generated codes are valid six-digit numeric strings in multiple attempts
        for _ in range(50):
            code = generate_verification_code()
            self.assertTrue(code.isdigit())
            self.assertEqual(len(code), 6)
            self.assertGreaterEqual(int(code), 100000)
            self.assertLessEqual(int(code), 999999)

    # パスワードをハッシュ化し、正しい元のパスワードとの照合が正常に成功することを検証します。
    # Verify that a password can be successfully hashed and verified.
    def test_hash_and_verify_password(self):
        # パスワードをハッシュ化し、そのハッシュ値を用いて元のパスワードを検証
        # Hash a password and verify it against the resulting hash string
        password_hash = hash_password("secret-password")
        self.assertTrue(verify_password("secret-password", password_hash))

    # パスワード照合処理において、誤ったパスワードを指定した場合は照合が拒否されることを検証します。
    # Verify that password verification rejects incorrect passwords.
    def test_verify_password_rejects_wrong_password(self):
        # 正しいパスワードから生成したハッシュ値に対して、誤ったパスワードで照合を行う
        # Verify incorrect password against a hash generated from the correct password
        password_hash = hash_password("correct-password")
        self.assertFalse(verify_password("wrong-password", password_hash))

    # パスワード照合処理において、不正な形式（ハッシュ値のフォーマットが崩れているものなど）のハッシュ値が渡された場合に安全に拒否されることを検証します。
    # Verify that password verification rejects malformed hash values safely.
    def test_verify_password_rejects_malformed_hash(self):
        # 不正なハッシュ文字列のフォーマットを渡して検証が失敗することを確認
        # Check that verification fails safely when given an invalid hash format string
        self.assertFalse(verify_password("password", "invalid-format"))

    # タイミング攻撃を防ぐための定数時間比較処理（constant_time_compare）が、値の同一性を正しく識別できることを検証します。
    # Verify that constant-time comparison correctly matches identical strings and rejects differing ones.
    def test_constant_time_compare(self):
        # 同一の値、および異なる値での比較結果の真偽値を検証
        # Verify true for identical strings and false for mismatched strings
        self.assertTrue(constant_time_compare("123456", "123456"))
        self.assertFalse(constant_time_compare("123456", "123457"))


if __name__ == "__main__":
    unittest.main()
