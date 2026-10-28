import { Skeleton, SkeletonText } from "../ui/skeleton";

// テーブルの各カラムのメタ情報を表す型
// Type representing metadata for each column of a database table
export type ColumnDetail = {
  name: string;
  type?: string | null;
  nullable?: boolean;
  key?: string | null;
  default?: string | number | null;
  extra?: string | null;
};

// 長いテキストが入るカラムは表示幅を広げる
// Columns known to hold long text get a wider cell
const WIDE_COLUMNS = new Set(["message", "content", "prompt_template", "input_examples", "output_examples"]);
// これを超えるセルは折りたたむ / Cells longer than this collapse
const COLLAPSE_AFTER_CHARS = 160;

const cellClass = (columnName: string) => (WIDE_COLUMNS.has(columnName) ? "admin-data-table__wide" : undefined);

function PreviewSkeleton() {
  return (
    <div className="admin-skeleton-stack" role="status" aria-label="管理データを読み込み中">
      <Skeleton variant="text" width="42%" height="1rem" />
      <SkeletonText lines={4} />
      <SkeletonText lines={6} />
    </div>
  );
}

function CellValue({ value }: { value: unknown }) {
  const text = value === null || value === undefined ? "" : String(value);
  if (text.length <= COLLAPSE_AFTER_CHARS) return <>{text}</>;
  const summary = text.slice(0, COLLAPSE_AFTER_CHARS).replace(/[\r\n]/g, " ");
  return (
    <details className="admin-cell-details">
      <summary>{summary}…</summary>
      {text}
    </details>
  );
}

type AdminTablePreviewProps = {
  loading: boolean;
  selectedTable: string;
  columnDetails: ColumnDetail[];
  columnNames: string[];
  rows: Array<Array<unknown>>;
};

// 選んだテーブルの定義と、先頭 100 行のデータを表で見せる
// Shows the selected table's definition and its first 100 rows
export function AdminTablePreview({ loading, selectedTable, columnDetails, columnNames, rows }: AdminTablePreviewProps) {
  let body;
  if (loading) {
    body = <PreviewSkeleton />;
  } else if (!selectedTable) {
    body = <p className="admin-empty">左の一覧から、内容を確認するテーブルを選んでください。</p>;
  } else {
    body = (
      <>
        <p className="admin-panel__lead">
          <strong>{selectedTable}</strong> の定義と、最大 100 行のデータを表示しています。
        </p>

        {columnDetails.length ? (
          <div className="admin-panel__block">
            <h4 className="admin-panel__subtitle">テーブル定義</h4>
            <div className="admin-table-scroll">
              <table className="admin-data-table">
                <thead>
                  <tr>
                    <th>カラム名</th>
                    <th>型</th>
                    <th>NULL</th>
                    <th>キー</th>
                    <th>デフォルト</th>
                    <th>追加情報</th>
                  </tr>
                </thead>
                <tbody>
                  {columnDetails.map((column) => (
                    <tr key={column.name}>
                      <td>{column.name}</td>
                      <td>{column.type}</td>
                      <td>{column.nullable ? "許可" : "不可"}</td>
                      <td>{column.key || "—"}</td>
                      <td>{column.default !== null && column.default !== undefined ? column.default : "—"}</td>
                      <td>{column.extra || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        <div className="admin-panel__block">
          <h4 className="admin-panel__subtitle">データ</h4>
          {columnNames.length ? (
            <div className="admin-table-scroll">
              <table className="admin-data-table">
                <thead>
                  <tr>
                    {columnNames.map((column) => (
                      <th className={cellClass(column)} key={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.length ? (
                    rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((value, colIndex) => (
                          <td className={cellClass(columnNames[colIndex])} key={`${rowIndex}-${colIndex}`}>
                            <CellValue value={value} />
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="admin-data-table__muted" colSpan={columnNames.length}>
                        表示できるデータがありません。
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="admin-empty">表示できるデータがありません。</p>
          )}
        </div>
      </>
    );
  }

  return (
    <section className="admin-panel" aria-labelledby="adminPreviewTitle">
      <h3 className="admin-panel__title" id="adminPreviewTitle">テーブルプレビュー</h3>
      {body}
    </section>
  );
}
