// フロントエンドサーバーの稼働確認用の API ルート（/api/healthz）。常に 200 と { status: "ok" } を返す。
// API route (/api/healthz) for checking that the frontend server is running; always responds 200 with { status: "ok" }.

import type { NextApiRequest, NextApiResponse } from "next";

// ヘルスチェックエンドポイント（フロントエンドサーバーの稼働確認用）
// Health check endpoint (to verify that the frontend server is running)
export default function handler(_: NextApiRequest, res: NextApiResponse) {
  res.status(200).json({ status: "ok" });
}
