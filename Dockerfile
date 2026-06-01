FROM python:3.12.12-slim

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

EXPOSE 5004

CMD ["/app/docker/app-entrypoint.sh"]
