import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.logging_config import (
    APP_LOG_HANDLER_NAME,
    CONSOLE_HANDLER_NAME,
    ERROR_LOG_HANDLER_NAME,
    configure_logging,
)


# 日本語: LoggingConfigTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to LoggingConfigTestCase.
class LoggingConfigTestCase(unittest.TestCase):
    # 日本語: setUp に関する処理の入口です。
    # English: Entry point for logic related to setUp.
    def setUp(self):
        self.root_logger = logging.getLogger()
        self.original_level = self.root_logger.level

        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for handler in list(self.root_logger.handlers):
            if getattr(handler, "name", "") in {
                CONSOLE_HANDLER_NAME,
                APP_LOG_HANDLER_NAME,
                ERROR_LOG_HANDLER_NAME,
            }:
                self.root_logger.removeHandler(handler)
                handler.close()

        self.original_handlers = list(self.root_logger.handlers)

    # 日本語: tearDown に関する処理の入口です。
    # English: Entry point for logic related to tearDown.
    def tearDown(self):
        # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
        # English: Process each target item in order and accumulate the needed result.
        for handler in list(self.root_logger.handlers):
            if getattr(handler, "name", "") in {
                CONSOLE_HANDLER_NAME,
                APP_LOG_HANDLER_NAME,
                ERROR_LOG_HANDLER_NAME,
            }:
                self.root_logger.removeHandler(handler)
                handler.close()

        self.root_logger.handlers = self.original_handlers
        self.root_logger.setLevel(self.original_level)

    # 日本語: test configure logging writes app and error files のテスト検証を担当します。
    # English: Handle verifying test behavior for test configure logging writes app and error files.
    def test_configure_logging_writes_app_and_error_files(self):
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {
                    "LOG_DIR": temp_dir,
                    "LOG_LEVEL": "INFO",
                    "LOG_MAX_BYTES": "1024",
                    "LOG_BACKUP_COUNT": "2",
                },
                clear=False,
            ):
                configure_logging()
                configure_logging()

                named_handlers = [
                    handler
                    for handler in self.root_logger.handlers
                    if getattr(handler, "name", "")
                    in {APP_LOG_HANDLER_NAME, ERROR_LOG_HANDLER_NAME}
                ]
                self.assertEqual(len(named_handlers), 2)

                logging.getLogger("tests.logging_config").error("file logging smoke test")
                for handler in named_handlers:
                    handler.flush()

            app_log = Path(temp_dir) / "app.log"
            error_log = Path(temp_dir) / "error.log"
            self.assertTrue(app_log.exists())
            self.assertTrue(error_log.exists())
            self.assertIn("file logging smoke test", app_log.read_text(encoding="utf-8"))
            self.assertIn("file logging smoke test", error_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
