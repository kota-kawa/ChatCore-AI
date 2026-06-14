from __future__ import annotations

import re
import unittest
from pathlib import Path

from scripts.generate_frontend_zod_schemas import get_schema_fingerprint


class GeneratedApiSchemasTestCase(unittest.TestCase):
    def test_generated_api_schema_fingerprint_matches_backend_models(self):
        generated_file = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "types"
            / "generated"
            / "api_schemas.ts"
        )
        content = generated_file.read_text(encoding="utf-8")
        match = re.search(r"^// Schema fingerprint: ([0-9a-f]{64})$", content, re.MULTILINE)
        self.assertIsNotNone(
            match,
            "Schema fingerprint is missing in generated api_schemas.ts.",
        )
        self.assertEqual(
            match.group(1),
            get_schema_fingerprint(),
            "Generated API schemas are out of date. Run `python3 scripts/generate_frontend_zod_schemas.py`.",
        )


if __name__ == "__main__":
    unittest.main()
