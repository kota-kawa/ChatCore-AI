from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.generate_frontend_zod_schemas import get_schema_fingerprint


class GeneratedApiSchemasTestCase(unittest.TestCase):
    """
    フロントエンドのZodスキーマが最新の状態であるかを検証するテストクラス
    Test class to verify that the frontend Zod schemas are up to date
    """

    def test_generated_api_schema_fingerprint_matches_backend_models(self):
        """
        生成されたZodスキーマのフィンガープリントが、バックエンドモデルから算出された現在の値と一致することを確認します。
        Verify that the fingerprint of the generated Zod schema matches the current value calculated from backend models.
        """
        # 生成されたZodスキーマファイルのパスを設定
        # Set the path to the generated Zod schema file
        generated_file = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "types"
            / "generated"
            / "api_schemas.ts"
        )
        # スキーマファイルの内容を読み込み
        # Read the content of the schema file
        content = generated_file.read_text(encoding="utf-8")
        
        # ファイルからフィンガープリントのハッシュ値を抽出
        # Extract the fingerprint hash value from the file
        match = re.search(r"^// Schema fingerprint: ([0-9a-f]{64})$", content, re.MULTILINE)
        
        # フィンガープリントが存在することを検証
        # Assert that the fingerprint is present
        self.assertIsNotNone(
            match,
            "Schema fingerprint is missing in generated api_schemas.ts.",
        )
        # 抽出したフィンガープリントが最新のスキーマ定義と一致するか検証
        # Assert that the extracted fingerprint matches the latest schema definition
        self.assertEqual(
            match.group(1),
            get_schema_fingerprint(),
            "Generated API schemas are out of date. Run `python3 scripts/generate_frontend_zod_schemas.py`.",
        )


if __name__ == "__main__":
    # テストの実行
    # Execute the tests
    unittest.main()
