import type { FormEvent } from "react";

import type { ColumnDetail } from "./admin_table_preview";

type SubmitForm = (event: FormEvent<HTMLFormElement>, endpoint: string) => void;

type AdminTableOperationsProps = {
  selectedTable: string;
  columnDetails: ColumnDetail[];
  dashboardError: string;
  onSubmit: SubmitForm;
};

// テーブル選択時はカラムの追加・削除、未選択時はテーブルの作成を出す。テーブルの削除は常に出す
// With a table selected, offers adding and dropping columns; otherwise creating a table. Dropping a
// table is always available
export function AdminTableOperations({ selectedTable, columnDetails, dashboardError, onSubmit }: AdminTableOperationsProps) {
  // カラムが1つしかないテーブルは、壊さないよう削除を禁止する
  // A table with a single column cannot lose it, so dropping is disabled
  const deleteDisabled = columnDetails.length <= 1;

  return (
    <section className="admin-panel" aria-labelledby="adminOperationsTitle">
      <h3 className="admin-panel__title" id="adminOperationsTitle">テーブル操作</h3>
      {selectedTable ? (
        <p className="admin-panel__lead"><strong>{selectedTable}</strong> のカラムを変更します。</p>
      ) : (
        <p className="admin-panel__lead">カラムを変更するときは、左の一覧からテーブルを選んでください。</p>
      )}

      {selectedTable ? (
        <>
          <div className="admin-panel__block">
            <h4 className="admin-panel__subtitle">カラムの追加</h4>
            <form className="admin-form" onSubmit={(event) => onSubmit(event, "/admin/api/add-column")}>
              <input type="hidden" name="table_name" value={selectedTable} />
              <div className="admin-field">
                <label className="admin-label" htmlFor="add-column-name">カラム名</label>
                <input type="text" id="add-column-name" name="column_name" required className="admin-input" />
              </div>
              <div className="admin-field">
                <label className="admin-label" htmlFor="add-column-type">カラム定義</label>
                <input
                  type="text"
                  id="add-column-type"
                  name="column_type"
                  required
                  className="admin-input"
                  aria-describedby="add-column-type-hint"
                />
                <p className="admin-hint" id="add-column-type-hint">例: VARCHAR(255) NOT NULL / NUMERIC(10,2) DEFAULT 0</p>
              </div>
              <div className="admin-form__actions">
                <button type="submit" className="admin-btn admin-btn--primary">カラムを追加</button>
              </div>
            </form>
          </div>

          <div className="admin-panel__block">
            <h4 className="admin-panel__subtitle">カラムの削除</h4>
            <form className="admin-form" onSubmit={(event) => onSubmit(event, "/admin/api/delete-column")}>
              <input type="hidden" name="table_name" value={selectedTable} />
              <div className="admin-field">
                <label className="admin-label" htmlFor="delete-column-name">削除するカラム</label>
                <select
                  id="delete-column-name"
                  name="column_name"
                  disabled={deleteDisabled}
                  required
                  defaultValue=""
                  className="admin-input"
                >
                  <option value="" disabled>カラムを選択</option>
                  {columnDetails.map((column) => (
                    <option value={column.name} key={column.name}>
                      {column.name}
                      {column.type ? ` (${column.type})` : ""}
                    </option>
                  ))}
                </select>
                {deleteDisabled ? (
                  <p className="admin-field-error">テーブルのカラムが1つしかないため削除できません。</p>
                ) : null}
              </div>
              <div className="admin-form__actions">
                <button type="submit" className="admin-btn" disabled={deleteDisabled}>カラムを削除</button>
              </div>
            </form>
          </div>
        </>
      ) : (
        <div className="admin-panel__block">
          <h4 className="admin-panel__subtitle">テーブルの作成</h4>
          <form className="admin-form" onSubmit={(event) => onSubmit(event, "/admin/api/create-table")}>
            <div className="admin-field">
              <label className="admin-label" htmlFor="create-table-name">テーブル名</label>
              <input type="text" id="create-table-name" name="table_name" required className="admin-input" />
            </div>
            <div className="admin-field">
              <label className="admin-label" htmlFor="column-definitions">カラム定義</label>
              <textarea
                id="column-definitions"
                name="columns"
                placeholder="id BIGSERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL"
                required
                className="admin-input admin-input--code"
                aria-describedby="column-definitions-hint"
              ></textarea>
              <p className="admin-hint" id="column-definitions-hint">
                PostgreSQL の基本的なカラム定義だけに対応しています。テーブルオプションは使えません。
              </p>
            </div>
            <div className="admin-form__actions">
              <button type="submit" className="admin-btn admin-btn--primary">作成</button>
            </div>
          </form>
        </div>
      )}

      {/* 誤操作を防ぐため、削除するテーブル名は手で入力させる / The table name is typed by hand to prevent mistakes */}
      <div className="admin-panel__block">
        <h4 className="admin-panel__subtitle">テーブルの削除</h4>
        <form className="admin-form" onSubmit={(event) => onSubmit(event, "/admin/api/delete-table")}>
          <div className="admin-field">
            <label className="admin-label" htmlFor="delete-table-name">削除するテーブル名</label>
            <input
              type="text"
              id="delete-table-name"
              name="table_name"
              required
              className="admin-input"
              aria-describedby="delete-table-hint"
            />
            <p className="admin-hint" id="delete-table-hint">元に戻せません。確認のため、テーブル名を正確に入力してください。</p>
          </div>
          <div className="admin-form__actions">
            <button type="submit" className="admin-btn">テーブルを削除</button>
          </div>
        </form>
      </div>

      {dashboardError ? (
        <div className="admin-panel__block">
          <p className="admin-notice admin-notice--error">エラー: {dashboardError}</p>
        </div>
      ) : null}
    </section>
  );
}
