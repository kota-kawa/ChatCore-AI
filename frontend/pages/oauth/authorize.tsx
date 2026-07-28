import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";

import { SeoHead } from "../../components/SeoHead";
import { useTranslation } from "../../contexts/locale_context";
import "../../scripts/core/csrf";
import {
  decideMcpOAuthConsent,
  loadMcpOAuthConsent,
  McpOAuthApiError
} from "../../scripts/user/settings/api";
import { MCP_OAUTH_SCOPE_DEFINITIONS, MCP_OAUTH_SCOPE_DEFINITIONS_EN } from "../../scripts/user/settings/constants";
import type { McpOAuthConsent } from "../../scripts/user/settings/types";

// MCP OAuth の認可画面。外部AIサービスに投稿権限を渡す前に、ユーザーへ接続先を明示する。
// MCP OAuth authorization page that clearly identifies the external AI service before granting publishing access.
export default function McpOAuthAuthorizePage() {
  const { locale } = useTranslation();
  const english = locale === "en";
  const router = useRouter();
  const request = useMemo(() => {
    const raw = router.query.request;
    return typeof raw === "string" ? raw : "";
  }, [router.query.request]);
  const [consent, setConsent] = useState<McpOAuthConsent | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const requestedPermissions = useMemo(() => {
    if (!consent) {
      return [];
    }
    const definitions = english ? MCP_OAUTH_SCOPE_DEFINITIONS_EN : MCP_OAUTH_SCOPE_DEFINITIONS;
    return consent.scope.split(/\s+/).filter(Boolean).map((scope) => ({
      scope,
      ...(definitions[scope] ?? {
        label: scope,
        description: english ? "Allow access to this permission." : "この権限へのアクセスを許可します。",
        iconClass: "bi bi-key"
      })
    }));
  }, [consent, english]);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }
    if (!request) {
      setErrorMessage(english ? "The authorization request was not found. Start the connection again from the AI service." : "認可リクエストが見つかりません。AIサービスからもう一度接続してください。");
      return;
    }

    let cancelled = false;
    const loadConsent = async () => {
      setConsent(null);
      setErrorMessage("");
      try {
        const nextConsent = await loadMcpOAuthConsent(request);
        if (!cancelled) {
          setConsent(nextConsent);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (error instanceof McpOAuthApiError && error.status === 401) {
          const nextPath = router.asPath.startsWith("/") ? router.asPath : "/oauth/authorize";
          window.location.replace(`/login?next=${encodeURIComponent(nextPath)}`);
          return;
        }
        setErrorMessage(error instanceof Error ? error.message : (english ? "Could not load the authorization details." : "認可情報の取得に失敗しました。"));
      }
    };

    void loadConsent();
    return () => {
      cancelled = true;
    };
  }, [english, request, router]);

  const decide = async (decision: "approve" | "deny") => {
    if (!request || submitting) {
      return;
    }

    setSubmitting(true);
    setErrorMessage("");
    try {
      const redirectUrl = await decideMcpOAuthConsent(request, decision);
      window.location.assign(redirectUrl);
    } catch (error) {
      if (error instanceof McpOAuthApiError && error.status === 401) {
        const nextPath = router.asPath.startsWith("/") ? router.asPath : "/oauth/authorize";
        window.location.replace(`/login?next=${encodeURIComponent(nextPath)}`);
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : (english ? "Could not complete the authorization request." : "認可操作に失敗しました。"));
      setSubmitting(false);
    }
  };

  return (
    <>
      <SeoHead
        title={english ? "Review AI service connection | Chat Core" : "AIサービス連携の確認 | Chat Core"}
        description={english ? "Review the Chat Core permissions requested by an external AI service." : "外部AIサービスへ許可するChat Coreの権限を確認します。"}
        canonicalPath="/oauth/authorize"
        noindex
      />

      <main className="oauth-authorize-page">
        <section className="oauth-authorize-card" aria-labelledby="oauth-authorize-title">
          <header className="oauth-authorize-card__header">
            <div className="oauth-authorize-brand" aria-label="Chat Core">
              <span className="oauth-authorize-brand__mark" aria-hidden="true"><img src="/static/favicon.png" alt="" /></span>
              <span>Chat Core</span>
            </div>
            {consent ? (
              <>
                <h1 id="oauth-authorize-title">{english ? `Connect to ${consent.client_name}?` : `${consent.client_name} と連携しますか？`}</h1>
                <p><strong>{consent.client_host || (english ? "Unknown source" : "不明な接続元")}</strong>{english ? " is requesting access to Chat Core." : " がChat Coreへのアクセスを求めています。"}</p>
              </>
            ) : (
              <h1 id="oauth-authorize-title">{english ? "Review AI service connection" : "AIサービス連携の確認"}</h1>
            )}
          </header>

          {errorMessage ? (
            <div className="oauth-authorize-message oauth-authorize-message--error" role="alert">
              <i className="bi bi-exclamation-octagon-fill" aria-hidden="true"></i>
              <div>
                <strong>{english ? "Could not verify the connection" : "連携情報を確認できませんでした"}</strong>
                <p>{errorMessage}</p>
              </div>
              <button type="button" className="oauth-authorize-retry" onClick={() => window.location.reload()}>
                {english ? "Reload" : "再読み込み"}
              </button>
            </div>
          ) : null}

          {!consent && !errorMessage ? (
            <div className="oauth-authorize-loading" aria-live="polite">
              <span className="oauth-authorize-loading__spinner" aria-hidden="true"></span>
              <span>{english ? "Securely checking the connection details…" : "連携情報を安全に確認しています…"}</span>
            </div>
          ) : null}

          {consent ? (
            <div className="oauth-authorize-content">
              <section className="oauth-authorize-permission" aria-labelledby="oauth-permission-title">
                <h2 id="oauth-permission-title">{english ? "Permissions for this connection" : "この連携で許可されること"}</h2>
                {requestedPermissions.map((permission) => (
                  <div className="oauth-authorize-permission__item" key={permission.scope}>
                    <span className="oauth-authorize-permission__icon" aria-hidden="true"><i className={permission.iconClass}></i></span>
                    <div>
                      <strong>{permission.label}</strong>
                      <p>{permission.description}</p>
                    </div>
                  </div>
                ))}
              </section>

              <div className="oauth-authorize-security-note">
                <i className="bi bi-info-circle" aria-hidden="true"></i>
                <p>{english ? "You can revoke this permission at any time under External service connections in Settings." : "この許可はいつでも設定画面の「外部サービス連携」から取り消せます。"}</p>
              </div>

              <details className="oauth-authorize-details">
                <summary>{english ? "Show connection details" : "接続の詳細を表示"}</summary>
                <dl>
                  <div><dt>{english ? "Source" : "接続元"}</dt><dd>{consent.client_host || (english ? "Unknown" : "不明")}</dd></div>
                  <div><dt>{english ? "Redirect destination" : "戻り先"}</dt><dd>{consent.redirect_host}</dd></div>
                  <div><dt>{english ? "Allowed scopes" : "許可するスコープ"}</dt><dd>{consent.scope}</dd></div>
                  <div><dt>{english ? "Client ID" : "クライアントID"}</dt><dd>{consent.client_id}</dd></div>
                </dl>
              </details>

              {consent.localhost_warning ? (
                <div className="oauth-authorize-message oauth-authorize-message--warning" role="alert">
                  <i className="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
                  <div>
                    <strong>{english ? "Connection to a local environment" : "ローカル環境への接続"}</strong>
                    <p>{english ? "This connection redirects to a local environment. Make sure you trust the AI service." : "この連携はローカル環境に戻ります。信頼できるAIサービスであることを確認してください。"}</p>
                  </div>
                </div>
              ) : null}

              <div className="oauth-authorize-actions">
                <button
                  type="button"
                  className="oauth-authorize-button oauth-authorize-button--deny"
                  disabled={submitting}
                  onClick={() => {
                    void decide("deny");
                  }}
                >
                  {english ? "Cancel" : "キャンセル"}
                </button>
                <button
                  type="button"
                  className="oauth-authorize-button oauth-authorize-button--approve"
                  disabled={submitting}
                  onClick={() => {
                    void decide("approve");
                  }}
                >
                  <i className="bi bi-check2-circle" aria-hidden="true"></i>
                  {submitting ? (english ? "Processing..." : "処理中...") : (english ? "Allow and connect" : "許可して接続")}
                </button>
              </div>
            </div>
          ) : null}
        </section>
      </main>
    </>
  );
}
