import asyncio
import io
import logging
import unittest

import httpx
from fastapi import FastAPI

from services.request_context import RequestContextFilter, RequestContextMiddleware


# HTTPリクエストのコンテキスト情報をログやレスポンスヘッダー（X-Request-ID等）へ追加するミドルウェアとフィルターの動作をテストするクラス。
# Test class to check the middleware and log filter adding request context details (e.g. X-Request-ID, path, method) to logs and headers.
class RequestContextMiddlewareTestCase(unittest.TestCase):
    # ロガーとハンドラーを初期化し、リクエストコンテキストフィルターを設定してテスト出力用ストリームを設定します。
    # Set up a temporary log handler with a request context filter and buffer for verifying log content.
    def setUp(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.addFilter(RequestContextFilter())
        self.handler.setFormatter(
            logging.Formatter("%(request_id)s %(request_method)s %(request_path)s %(message)s")
        )
        self.logger = logging.getLogger("tests.request_context")
        self.original_handlers = list(self.logger.handlers)
        self.original_level = self.logger.level
        self.original_propagate = self.logger.propagate
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    # テスト終了後にロガーの設定を元に戻し、一時ハンドラーをクローズします。
    # Clean up log handlers and restore original logging configurations.
    def tearDown(self):
        self.handler.close()
        self.logger.handlers = self.original_handlers
        self.logger.setLevel(self.original_level)
        self.logger.propagate = self.original_propagate

    # リクエストIDヘッダーを送信したとき、それがレスポンスヘッダーに返り、ロガーから出力されるメッセージにリクエストIDやパス情報が動的に埋め込まれていることを検証します。
    # Verify that the X-Request-ID header is propagated to the response and injected into the log output details (id, method, path).
    def test_request_context_sets_response_header_and_log_fields(self):
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        # テスト用のダミールーティングエンドポイント関数。
        # Dummy routing endpoint function for testing.
        @app.get("/ping")
        async def ping():
            # ルート内でログを出力し、ミドルウェアによるコンテキスト追加効果を発生させる
            # Output logs inside the route to trigger the middleware context additions
            self.logger.info("inside route")
            return {"status": "ok"}

        # HTTPリクエストテスト用の非同期シナリオを実行する関数。
        # Function to perform test HTTP requests in an async environment.
        async def scenario():
            # ASGIトランスポートを使用してFastAPIアプリをモック接続
            # Mock connect to the FastAPI app using the ASGITransport
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                response = await client.get("/ping", headers={"X-Request-ID": "req-123"})

            # レスポンスヘッダーにリクエストIDが引き継がれていることを確認
            # Verify the response status code and that the X-Request-ID header is propagated
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Request-ID"], "req-123")

        # 非同期テストシナリオの実行
        # Execute the async test scenario
        asyncio.run(scenario())

        # ログメッセージ内にリクエストID、メソッド、パスが正しく含まれているか検証
        # Verify request ID, method, and path are correctly formatted in the log output
        self.assertIn("req-123 GET /ping inside route", self.stream.getvalue())


if __name__ == "__main__":
    unittest.main()
