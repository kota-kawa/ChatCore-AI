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


class LoggingConfigTestCase(unittest.TestCase):
    """
    ロギング設定の初期化、ハンドラーの追加、ログファイルの生成、出力の検証などを行うテストクラス。
    Test case class to verify the functionality and initialization of Logging Config.
    """

    def setUp(self):
        """
        テスト実行前の準備として、既存のルートロガーからテスト対象ハンドラーを除去し退避します。
        Save the root logger state and remove target logging handlers before running each test.
        """
        self.root_logger = logging.getLogger()
        self.original_level = self.root_logger.level

        # テスト対象のハンドラーが存在する場合は、一度除去してクローズ
        # Remove and close target handlers if they exist
        for handler in list(self.root_logger.handlers):
            if getattr(handler, "name", "") in {
                CONSOLE_HANDLER_NAME,
                APP_LOG_HANDLER_NAME,
                ERROR_LOG_HANDLER_NAME,
            }:
                self.root_logger.removeHandler(handler)
                handler.close()

        self.original_handlers = list(self.root_logger.handlers)

    def tearDown(self):
        """
        テスト終了後のクリーンアップとして、生成されたハンドラーを除去し、オリジナルのハンドラー構成を復元します。
        Clean up generated handlers and restore the original root logger configuration after each test.
        """
        # 作成されたテスト対象のハンドラーを除去してクローズ
        # Remove and close handlers created during the test
        for handler in list(self.root_logger.handlers):
            if getattr(handler, "name", "") in {
                CONSOLE_HANDLER_NAME,
                APP_LOG_HANDLER_NAME,
                ERROR_LOG_HANDLER_NAME,
            }:
                self.root_logger.removeHandler(handler)
                handler.close()

        # オリジナルの構成に戻す
        # Restore original configuration
        self.root_logger.handlers = self.original_handlers
        self.root_logger.setLevel(self.original_level)

    def test_configure_logging_writes_app_and_error_files(self):
        """
        ロギング設定関数を実行した際、app.log および error.log が正しく出力先ディレクトリに生成され、ログが記録されることを検証します。
        Verify that configure_logging successfully creates app.log and error.log files and logs error messages to both.
        """
        # 一時ディレクトリを作成して環境変数をモック
        # Create a temporary directory and mock environment variables
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
                # 初期設定の呼び出し（複数呼び出されても重複追加されないか検証するため2回呼ぶ）
                # Call configure logging twice to verify it handles duplicate registration correctly
                configure_logging()
                configure_logging()

                # 登録されたハンドラーから追加されたハンドラーを抽出
                # Extract handlers created by the configuration
                named_handlers = [
                    handler
                    for handler in self.root_logger.handlers
                    if getattr(handler, "name", "")
                    in {APP_LOG_HANDLER_NAME, ERROR_LOG_HANDLER_NAME}
                ]
                self.assertEqual(len(named_handlers), 2)

                # テスト用のエラーログを出力
                # Output a test error message
                logging.getLogger("tests.logging_config").error("file logging smoke test")
                for handler in named_handlers:
                    handler.flush()

            # ログファイルが作成されているか、またメッセージが含まれているかを検証
            # Verify log files exist and contain the logged message
            app_log = Path(temp_dir) / "app.log"
            error_log = Path(temp_dir) / "error.log"
            self.assertTrue(app_log.exists())
            self.assertTrue(error_log.exists())
            self.assertIn("file logging smoke test", app_log.read_text(encoding="utf-8"))
            self.assertIn("file logging smoke test", error_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    # テストを実行します
    # Execute the tests
    unittest.main()
