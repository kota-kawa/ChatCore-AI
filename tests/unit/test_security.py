import unittest

from services.security import (
    constant_time_compare,
    generate_verification_code,
    hash_password,
    verify_password,
)


# 日本語: Security Utilsの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Security Utils.
class SecurityUtilsTestCase(unittest.TestCase):
    # 日本語: generate検証コードがsixdigitsことを検証します。
    # English: Verify that generate verification code is six digits.
    def test_generate_verification_code_is_six_digits(self):
        # 日本語: 各対象データを順に処理し、検証を行います。
        for _ in range(50):
            code = generate_verification_code()
            self.assertTrue(code.isdigit())
            self.assertEqual(len(code), 6)
            self.assertGreaterEqual(int(code), 100000)
            self.assertLessEqual(int(code), 999999)

    # 日本語: および検証パスワード、hashことを検証します。
    # English: Verify that hash and verify password.
    def test_hash_and_verify_password(self):
        password_hash = hash_password("secret-password")
        self.assertTrue(verify_password("secret-password", password_hash))

    # 日本語: 検証パスワード拒否する誤ったパスワードことを検証します。
    # English: Verify that verify password rejects wrong password.
    def test_verify_password_rejects_wrong_password(self):
        password_hash = hash_password("correct-password")
        self.assertFalse(verify_password("wrong-password", password_hash))

    # 日本語: 検証パスワード拒否するmalformedhashことを検証します。
    # English: Verify that verify password rejects malformed hash.
    def test_verify_password_rejects_malformed_hash(self):
        self.assertFalse(verify_password("password", "invalid-format"))

    # 日本語: constanttimecompareことを検証します。
    # English: Verify that constant time compare.
    def test_constant_time_compare(self):
        self.assertTrue(constant_time_compare("123456", "123456"))
        self.assertFalse(constant_time_compare("123456", "123457"))


if __name__ == "__main__":
    unittest.main()
