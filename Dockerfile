# アプリ本体（FastAPI/uvicorn）の本番用コンテナイメージ。依存を固定版で入れ、非 root ユーザーで起動する。
# Production container image for the app (FastAPI/uvicorn): installs pinned dependencies and runs as a non-root user.
# 依存は requirements.lock を制約にして再現可能にする。コード（COPY . .）より先に入れ、変更が無ければ層キャッシュを再利用する。
# Dependencies are pinned through requirements.lock and installed before the source copy so the layer cache is reused.
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

# [JP] 非root実行に切り替える。アプリが書き込むのは logs/、prompt-share・
#      アバター・チャット画像のアップロード先（いずれもボリュームマウント点）、manual の埋め込み
#      キャッシュだけなので、そこだけ所有権を移し、コード本体は root 所有の
#      読み取り専用のまま残す。旧アバター保存先（frontend/public/static/uploads）
#      は読み取り専用の互換パスになったため、所有権は移さない。
# [EN] Switch to a non-root user. The app only writes to logs/, the prompt-share,
#      avatar and chat image upload directories (all volume mount points) and the manual
#      embedding cache, so only those change ownership; the source tree stays
#      root-owned and read-only for the runtime user. The former avatar location
#      under frontend/public/static/uploads is now a read-only compatibility path.
RUN groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin appuser \
    && mkdir -p \
        /app/logs \
        /app/data/uploads/prompt_share \
        /app/data/uploads/avatars \
        /app/data/uploads/chat_images \
        /app/docs/manual \
    && chown -R appuser:appuser \
        /app/logs \
        /app/data \
        /app/docs/manual

USER appuser

EXPOSE 5004

CMD ["/app/docker/app-entrypoint.sh"]
