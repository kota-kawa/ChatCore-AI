import { useRouter } from "next/router";
import { SeoHead } from "../../../SeoHead";

export function AuthGatewayHead() {
  const router = useRouter();
  return (
    <SeoHead
      title="ログイン・新規登録 | Chat Core"
      description="Chat Coreのログイン・新規登録ページです。"
      canonicalPath={router.pathname}
      noindex
    />
  );
}
