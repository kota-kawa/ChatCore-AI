# Next.js フロントエンドの本番用イメージ。deps（依存の取得）→ builder（next build）→ runner（next start）の3段で、実行用には成果物だけを持ち込む。
# Production image for the Next.js frontend, in three stages: deps (install dependencies) -> builder (next build) -> runner (next start); only build output reaches the final image.
FROM node:24.17.0-alpine AS deps

WORKDIR /app

# 依存だけを先に入れておくと、ソースだけが変わったときに npm ci のレイヤーキャッシュが効く。
# Installing dependencies first lets the npm ci layer stay cached when only the source changes.
COPY package.json package-lock.json ./
RUN npm ci

# ビルド段。BACKEND_URL などは ARG で受け、next build が参照できるよう ENV にも設定する。
# Build stage. BACKEND_URL and friends come in as ARGs and are also set as ENV so next build can read them.
FROM node:24.17.0-alpine AS builder

WORKDIR /app

ARG BACKEND_URL=http://app:5004
ARG NEXT_PUBLIC_SITE_URL=https://chatcore-ai.com
ARG NEXT_PUBLIC_GA_MEASUREMENT_ID=G-Q1F9PY8BFJ
ENV BACKEND_URL=${BACKEND_URL}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
ENV NEXT_PUBLIC_GA_MEASUREMENT_ID=${NEXT_PUBLIC_GA_MEASUREMENT_ID}

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# 実行段。ビルド段から実行に必要なものだけをコピーする。ここでの ENV はコンテナ実行時の既定値。
# Runtime stage. Copies only what is needed to run from the build stage; the ENV values here are the container's runtime defaults.
FROM node:24.17.0-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV BACKEND_URL=http://app:5004
ENV NEXT_PUBLIC_SITE_URL=https://chatcore-ai.com
ENV NEXT_PUBLIC_GA_MEASUREMENT_ID=G-Q1F9PY8BFJ

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/package-lock.json ./package-lock.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.mjs ./next.config.mjs

# [JP] node:alpine 同梱の非rootユーザーで実行する。next start は画像最適化の
#      キャッシュを .next/cache へ書くため、そこだけ所有権を移す。
# [EN] Run as the non-root user shipped with node:alpine. next start writes the
#      image-optimization cache under .next/cache, so hand that tree to it.
RUN mkdir -p /app/.next/cache && chown -R node:node /app/.next

USER node

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
