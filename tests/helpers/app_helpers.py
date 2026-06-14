from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware


# 日本語: build session test app の組み立て処理を担当します。
# English: Handle building for build session test app.
def build_session_test_app(*routers, secret_key="endpoint-test-secret", include_test_session_route=False):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=secret_key)

    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for router in routers:
        app.include_router(router)

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if include_test_session_route:

        # 日本語: set test session の設定処理を非同期で担当します。
        # English: Handle setting for set test session asynchronously.
        @app.post("/_test/session")
        async def set_test_session(request: Request):
            payload = await request.json()
            # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
            # English: Process each target item in order and accumulate the needed result.
            for key, value in payload.items():
                request.session[key] = value
            return {"status": "ok"}

    return app

