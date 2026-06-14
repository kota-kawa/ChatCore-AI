import asyncio
import io
import logging
import unittest

import httpx
from fastapi import FastAPI

from services.request_context import RequestContextFilter, RequestContextMiddleware


# 日本語: RequestContextMiddlewareTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to RequestContextMiddlewareTestCase.
class RequestContextMiddlewareTestCase(unittest.TestCase):
    # 日本語: setUp に関する処理の入口です。
    # English: Entry point for logic related to setUp.
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

    # 日本語: tearDown に関する処理の入口です。
    # English: Entry point for logic related to tearDown.
    def tearDown(self):
        self.handler.close()
        self.logger.handlers = self.original_handlers
        self.logger.setLevel(self.original_level)
        self.logger.propagate = self.original_propagate

    # 日本語: test request context sets response header and log fields のテスト検証を担当します。
    # English: Handle verifying test behavior for test request context sets response header and log fields.
    def test_request_context_sets_response_header_and_log_fields(self):
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        # 日本語: ping に関する処理の入口です。
        # English: Entry point for logic related to ping.
        @app.get("/ping")
        async def ping():
            self.logger.info("inside route")
            return {"status": "ok"}

        # 日本語: scenario に関する処理の入口です。
        # English: Entry point for logic related to scenario.
        async def scenario():
            # 日本語: 非同期コンテキスト内で必要なリソースを利用します。
            # English: Use the required resource inside the asynchronous context.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                response = await client.get("/ping", headers={"X-Request-ID": "req-123"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Request-ID"], "req-123")

        asyncio.run(scenario())

        self.assertIn("req-123 GET /ping inside route", self.stream.getvalue())


if __name__ == "__main__":
    unittest.main()
