import type { NextApiRequest, NextApiResponse } from "next";

// ヘルスチェックエンドポイント（フロントエンドサーバーの稼働確認用）
// Health check endpoint (to verify that the frontend server is running)
export default function handler(_: NextApiRequest, res: NextApiResponse) {
  res.status(200).json({ status: "ok" });
}
