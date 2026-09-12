FROM python:3.14.6-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=5004

COPY requirements-build.txt requirements.txt requirements.lock ./

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements-build.txt \
    && pip install --no-cache-dir -r requirements.txt -c requirements.lock

COPY wait-for-it.sh /wait-for-it.sh
RUN chmod +x /wait-for-it.sh

COPY . .

RUN chmod +x /app/docker/app-entrypoint.sh

# [JP] 非root実行に切り替える。アプリが書き込むのは logs/、prompt-share の
#      アップロード先（ボリュームマウント点）、アバター保存先、manual の埋め込み
#      キャッシュだけなので、そこだけ所有権を移し、コード本体は root 所有の
#      読み取り専用のまま残す。
# [EN] Switch to a non-root user. The app only writes to logs/, the prompt-share
#      upload directory (a volume mount point), the avatar upload directory and
#      the manual embedding cache, so only those change ownership; the source
#      tree stays root-owned and read-only for the runtime user.
RUN groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin appuser \
    && mkdir -p \
        /app/logs \
        /app/data/uploads/prompt_share \
        /app/frontend/public/static/uploads \
        /app/docs/manual \
    && chown -R appuser:appuser \
        /app/logs \
        /app/data \
        /app/frontend/public/static/uploads \
        /app/docs/manual

USER appuser

EXPOSE 5004

CMD ["/app/docker/app-entrypoint.sh"]
