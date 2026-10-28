import { useEffect, useState, type FormEvent } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { DemoCodesUnauthorizedError, useDemoAccessCodes } from "../../hooks/use_demo_access_codes";
import type { DemoAccessCodeApi } from "../../types/generated/api_schemas";
import { CopyButton } from "../ui/copy_button";
import { ModalShell } from "../ui/modal_shell";
import { DemoCodeList } from "./demo_code_list";

// 発行直後だけ手元に持つコードの平文。サーバーには保存されず、あとから取り出せない
// The plain code held only right after issuing; the server keeps just its hash, so it can't be fetched again
type IssuedCode = { code: string; label: string };

// 管理画面の「デモ用アクセスコード」。応募先ごとのコードの発行・一覧・停止を行う
// The admin "Demo access codes" card: issue, list and stop one code per recipient
export function DemoCodesPanel({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { t } = useTranslation();
  const { codes, error: loadError, isLoading, issuing, revokingId, issue, revoke } = useDemoAccessCodes({
    loadFailed: t("admin.demoLoadFailed"),
    issueFailed: t("admin.demoIssueFailed"),
    revokeFailed: t("admin.demoRevokeFailed")
  });
  const [label, setLabel] = useState("");
  const [issued, setIssued] = useState<IssuedCode | null>(null);
  const [formError, setFormError] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<DemoAccessCodeApi | null>(null);
  const [revokeError, setRevokeError] = useState("");

  useEffect(() => {
    if (loadError instanceof DemoCodesUnauthorizedError) onUnauthorized();
  }, [loadError, onUnauthorized]);

  // 401 は管理者ログインへ戻し、それ以外はサーバーの文言を呼び出し元の表示欄へ渡す
  // Send a 401 back to the admin login; otherwise hand the server's message to the caller's error slot
  const reportFailure = (caught: unknown, show: (message: string) => void) => {
    if (caught instanceof DemoCodesUnauthorizedError) {
      onUnauthorized();
      return;
    }
    show(caught instanceof Error ? caught.message : t("admin.demoIssueFailed"));
  };

  const handleIssue = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedLabel = label.trim();
    if (!trimmedLabel) {
      setFormError(t("admin.demoLabelRequired"));
      return;
    }
    setFormError("");
    try {
      const result = await issue(trimmedLabel);
      setIssued({ code: result.code, label: result.item.label });
      setLabel("");
    } catch (caught) {
      reportFailure(caught, setFormError);
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    setRevokeError("");
    try {
      await revoke(revokeTarget.id);
      setRevokeTarget(null);
    } catch (caught) {
      reportFailure(caught, setRevokeError);
    }
  };

  const closeRevokeDialog = () => {
    setRevokeTarget(null);
    setRevokeError("");
  };

  let list;
  if (loadError && !(loadError instanceof DemoCodesUnauthorizedError)) {
    list = <p className="demo-codes__error" role="alert">{loadError.message}</p>;
  } else if (isLoading) {
    list = <p className="demo-codes__empty">{t("common.loading")}</p>;
  } else if (codes.length === 0) {
    list = <p className="demo-codes__empty">{t("admin.demoEmpty")}</p>;
  } else {
    list = <DemoCodeList codes={codes} revokingId={revokingId} onRevoke={setRevokeTarget} />;
  }

  return (
    <section className="demo-codes" aria-labelledby="demoCodesTitle">
      <link rel="stylesheet" href="/static/css/pages/admin/demo_codes.css" precedence="demo-codes" />
      <h2 className="demo-codes__title" id="demoCodesTitle">{t("admin.demoTitle")}</h2>
      <p className="demo-codes__lead">{t("admin.demoLead")}</p>

      <form className="demo-codes__form" onSubmit={(event) => void handleIssue(event)}>
        <label className="demo-codes__label" htmlFor="demoCodeLabel">{t("admin.demoLabelField")}</label>
        <div className="demo-codes__form-row">
          <input
            id="demoCodeLabel"
            className="demo-codes__input"
            type="text"
            maxLength={120}
            placeholder={t("admin.demoLabelPlaceholder")}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            disabled={issuing}
          />
          <button type="submit" className="demo-codes__btn demo-codes__btn--primary" disabled={issuing || !label.trim()}>
            {issuing ? t("admin.demoIssuing") : t("admin.demoIssue")}
          </button>
        </div>
        {formError ? <p className="demo-codes__error" role="alert">{formError}</p> : null}
      </form>

      {issued ? (
        <div className="demo-codes__issued" role="status">
          <p className="demo-codes__issued-title">{t("admin.demoIssuedTitle", { label: issued.label })}</p>
          <div className="demo-codes__code-row">
            <code className="demo-codes__code">{issued.code}</code>
            <CopyButton
              className="demo-codes__copy"
              getText={() => issued.code}
              label={t("admin.demoCopy")}
              copiedLabel={t("admin.demoCopied")}
            />
          </div>
          <p className="demo-codes__issued-note">{t("admin.demoIssuedWarning")}</p>
          <div className="demo-codes__issued-actions">
            <button type="button" className="demo-codes__btn" onClick={() => setIssued(null)}>{t("common.close")}</button>
          </div>
        </div>
      ) : null}

      <h3 className="demo-codes__subtitle">{t("admin.demoListTitle")}</h3>
      {list}

      {revokeTarget ? (
        <ModalShell
          isOpen
          onClose={closeRevokeDialog}
          className="cc-modal"
          labelledBy="demoCodeRevokeTitle"
          dismissDisabled={revokingId !== null}
        >
          <div className="cc-modal__panel cc-modal__panel--sm" tabIndex={-1}>
            <header className="cc-modal__header">
              <div className="cc-modal__heading">
                <h2 className="cc-modal__title" id="demoCodeRevokeTitle">{t("admin.demoRevokeTitle")}</h2>
              </div>
            </header>
            <div className="cc-modal__body">
              <p>{t("admin.demoRevokeBody", { label: revokeTarget.label })}</p>
              {revokeError ? <p className="demo-codes__error" role="alert">{revokeError}</p> : null}
            </div>
            <footer className="cc-modal__footer">
              <button type="button" className="cc-modal__btn" onClick={closeRevokeDialog} disabled={revokingId !== null}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="cc-modal__btn cc-modal__btn--primary"
                onClick={() => void handleRevoke()}
                disabled={revokingId !== null}
              >
                {revokingId !== null ? t("admin.demoRevoking") : t("admin.demoRevokeConfirm")}
              </button>
            </footer>
          </div>
        </ModalShell>
      ) : null}
    </section>
  );
}
