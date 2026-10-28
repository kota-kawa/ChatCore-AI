import { useTranslation } from "../../contexts/locale_context";
import type { MessageKey } from "../../lib/i18n/catalogs/ja";
import type { DemoAccessCodeApi } from "../../types/generated/api_schemas";

const STATUS_LABEL_KEYS: Record<DemoAccessCodeApi["status"], MessageKey> = {
  unused: "admin.demoStatusUnused",
  active: "admin.demoStatusActive",
  ended: "admin.demoStatusEnded",
  revoked: "admin.demoStatusRevoked"
};

// 日付の区切りは、利用枠の画面と同じく日本時間に固定する
// Date boundaries use Japan time, like the usage screen
const DATE_OPTIONS: Intl.DateTimeFormatOptions = { year: "numeric", month: "numeric", day: "numeric", timeZone: "Asia/Tokyo" };

type DemoCodeListProps = {
  codes: DemoAccessCodeApi[];
  revokingId: number | null;
  onRevoke: (code: DemoAccessCodeApi) => void;
};

// 発行済みコードの一覧。広い画面は表、スマホ幅は1件1枚のカードに積む（CSS側で切り替える）
// The issued codes: a table on wide screens, one stacked card per code on phones (switched in CSS)
export function DemoCodeList({ codes, revokingId, onRevoke }: DemoCodeListProps) {
  const { t, formatDate } = useTranslation();
  const dateOrDash = (value: string | null) => (value ? formatDate(value, DATE_OPTIONS) : "—");
  const usd = (value: number) => `$${value.toFixed(2)}`;

  return (
    <table className="demo-codes__table">
      <thead>
        <tr>
          <th scope="col">{t("admin.demoColLabel")}</th>
          <th scope="col">{t("admin.demoColStatus")}</th>
          <th scope="col">{t("admin.demoColFirstUsed")}</th>
          <th scope="col">{t("admin.demoColExpires")}</th>
          <th scope="col">{t("admin.demoColSpend")}</th>
          <th scope="col">{t("admin.demoColAction")}</th>
        </tr>
      </thead>
      <tbody>
        {codes.map((code) => {
          const canRevoke = code.status === "unused" || code.status === "active";
          return (
            <tr key={code.id}>
              <td className="demo-codes__cell-label">{code.label}</td>
              <td data-label={t("admin.demoColStatus")}>
                <span className={`demo-codes__badge demo-codes__badge--${code.status}`}>{t(STATUS_LABEL_KEYS[code.status])}</span>
              </td>
              <td data-label={t("admin.demoColFirstUsed")}>{dateOrDash(code.first_used_at)}</td>
              <td data-label={t("admin.demoColExpires")}>{dateOrDash(code.expires_at)}</td>
              <td data-label={t("admin.demoColSpend")}>
                {code.used_usd !== null ? `${usd(code.used_usd)} / ${usd(code.limit_usd)}` : "—"}
              </td>
              <td className="demo-codes__cell-action">
                {canRevoke ? (
                  <button
                    type="button"
                    className="admin-btn"
                    aria-label={t("admin.demoRevokeAria", { label: code.label })}
                    disabled={revokingId !== null}
                    onClick={() => onRevoke(code)}
                  >
                    {t("admin.demoRevoke")}
                  </button>
                ) : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
