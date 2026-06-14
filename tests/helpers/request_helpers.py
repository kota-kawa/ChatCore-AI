import json

from starlette.requests import Request


# 日本語: テスト用にカスタマイズされたASGIリクエスト（Starlette/FastAPI Request）オブジェクトを疑似的に構築します。
# English: Construct a mock ASGI request (Starlette/FastAPI Request) object customized for unit testing.
def build_request(
    *,
    method="GET",
    path="/",
    session=None,
    json_body=None,
    raw_body=None,
    query_string=b"",
    headers=None,
    scheme="http",
    host_header=None,
    server_host="testserver",
    server_port=80,
):
    # 日本語: ペイロードの指定方法（JSON形式とバイト列形式）が競合していないことを確認します。
    # English: Verify that the payload specification methods (JSON format and raw bytes format) do not conflict.
    if json_body is not None and raw_body is not None:
        raise ValueError("json_body and raw_body are mutually exclusive")

    # 日本語: 引数の種類に応じてリクエストボディをバイト列として初期化します。
    # English: Initialize the request body as bytes based on the type of argument provided.
    if raw_body is not None:
        body = raw_body
    elif json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
    else:
        body = b""

    # 日本語: リクエストヘッダーを初期化し、必要に応じてContent-TypeやHostヘッダーを追加します。
    # English: Initialize request headers and append Content-Type or Host headers if not already set.
    request_headers = list(headers or [])
    if json_body is not None and not any(key.lower() == b"content-type" for key, _ in request_headers):
        request_headers.append((b"content-type", b"application/json"))
    if host_header and not any(key.lower() == b"host" for key, _ in request_headers):
        request_headers.append((b"host", host_header.encode("utf-8")))

    # 日本語: ASGIスコープ（HTTPリクエストの接続コンテキスト情報）を定義します。
    # English: Define the ASGI scope dictionary, containing connection context information for the HTTP request.
    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": request_headers,
        "client": ("testclient", 50000),
        "server": (server_host, server_port),
        "session": session or {},
    }

    # 日本語: リクエストボディの読み込みを行うための非同期ASGI受信関数です。
    # English: Asynchronous ASGI receive function used to read the request body bytes.
    async def receive():
        nonlocal body
        # 日本語: すでにデータを読み取り済みの場合は空のボディを返却します。
        # English: Return an empty body if the request data has already been fully read.
        if body is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        current = body
        body = None
        return {"type": "http.request", "body": current, "more_body": False}

    return Request(scope, receive)


