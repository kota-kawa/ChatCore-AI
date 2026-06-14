from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware


# 日本語: テスト用のFastAPIアプリケーションインスタンスを構築します。SessionMiddlewareを追加し、指定されたルーターを登録します。
# English: Build a FastAPI application instance for testing. Adds SessionMiddleware and registers the specified routers.
def build_session_test_app(*routers, secret_key="endpoint-test-secret", include_test_session_route=False):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=secret_key)

    # 日本語: 提供されたすべてのルーターをFastAPIアプリに登録します。
    # English: Register all provided routers to the FastAPI app.
    for router in routers:
        app.include_router(router)

    # 日本語: テスト中にセッションデータを動的に設定するためのヘルパールートを有効にするか判定します。
    # English: Check if the helper route for dynamically setting session data during tests should be enabled.
    if include_test_session_route:

        # 日本語: テスト用クライアントから送信されたJSONペイロードの内容を、リクエストのセッションに直接書き込むためのテスト専用APIエンドポイントです。
        # English: A test-only API endpoint that directly writes the JSON payload sent by the test client into the request session.
        @app.post("/_test/session")
        async def set_test_session(request: Request):
            payload = await request.json()
            # 日本語: 送信されたすべてのキーと値のペアをリクエストのセッションに保存します。
            # English: Save all sent key-value pairs into the request session.
            for key, value in payload.items():
                request.session[key] = value
            return {"status": "ok"}

    return app


