import json

from starlette.requests import Request


# 日本語: build request の組み立て処理を担当します。
# English: Handle building for build request.
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
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if json_body is not None and raw_body is not None:
        raise ValueError("json_body and raw_body are mutually exclusive")

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if raw_body is not None:
        body = raw_body
    elif json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
    else:
        body = b""

    request_headers = list(headers or [])
    if json_body is not None and not any(key.lower() == b"content-type" for key, _ in request_headers):
        request_headers.append((b"content-type", b"application/json"))
    if host_header and not any(key.lower() == b"host" for key, _ in request_headers):
        request_headers.append((b"host", host_header.encode("utf-8")))

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

    # 日本語: receive に関する処理の入口です。
    # English: Entry point for logic related to receive.
    async def receive():
        nonlocal body
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if body is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        current = body
        body = None
        return {"type": "http.request", "body": current, "more_body": False}

    return Request(scope, receive)

