import unittest

from services.security import (
    constant_time_compare,
    generate_verification_code,
)


# 認証コード生成やタイミング攻撃防止用比較処理などのセキュリティ機能ユーティリティを検証するテストクラス。
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

    # タイミング攻撃を防ぐための定数時間比較処理（constant_time_compare）が、値の同一性を正しく識別できることを検証します。
    # Verify that constant-time comparison correctly matches identical strings and rejects differing ones.
    def test_constant_time_compare(self):
        # 同一の値、および異なる値での比較結果の真偽値を検証
        # Verify true for identical strings and false for mismatched strings
        self.assertTrue(constant_time_compare("123456", "123456"))
        self.assertFalse(constant_time_compare("123456", "123457"))


if __name__ == "__main__":
    unittest.main()
