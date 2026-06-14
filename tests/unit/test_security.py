import unittest

from services.security import (
    constant_time_compare,
    generate_verification_code,
    hash_password,
    verify_password,
)


# 日本語: SecurityUtilsTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to SecurityUtilsTestCase.
class SecurityUtilsTestCase(unittest.TestCase):
    # 日本語: test generate verification code is six digits のテスト検証を担当します。
    # English: Handle verifying test behavior for test generate verification code is six digits.
    def test_generate_verification_code_is_six_digits(self):
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for _ in range(50):
            code = generate_verification_code()
            self.assertTrue(code.isdigit())
            self.assertEqual(len(code), 6)
            self.assertGreaterEqual(int(code), 100000)
            self.assertLessEqual(int(code), 999999)

    # 日本語: test hash and verify password のテスト検証を担当します。
    # English: Handle verifying test behavior for test hash and verify password.
    def test_hash_and_verify_password(self):
        password_hash = hash_password("secret-password")
        self.assertTrue(verify_password("secret-password", password_hash))

    # 日本語: test verify password rejects wrong password のテスト検証を担当します。
    # English: Handle verifying test behavior for test verify password rejects wrong password.
    def test_verify_password_rejects_wrong_password(self):
        password_hash = hash_password("correct-password")
        self.assertFalse(verify_password("wrong-password", password_hash))

    # 日本語: test verify password rejects malformed hash のテスト検証を担当します。
    # English: Handle verifying test behavior for test verify password rejects malformed hash.
    def test_verify_password_rejects_malformed_hash(self):
        self.assertFalse(verify_password("password", "invalid-format"))

    # 日本語: test constant time compare のテスト検証を担当します。
    # English: Handle verifying test behavior for test constant time compare.
    def test_constant_time_compare(self):
        self.assertTrue(constant_time_compare("123456", "123456"))
        self.assertFalse(constant_time_compare("123456", "123457"))


if __name__ == "__main__":
    unittest.main()
