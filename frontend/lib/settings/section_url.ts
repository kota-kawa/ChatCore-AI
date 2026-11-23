// 設定ページで開いているセクションを URL のクエリと同期させるための小さなヘルパー群。
// URL に載せておくことで、再読み込みや共有リンクからでも同じセクションが開く。
// Small helpers that keep the opened settings section in sync with the URL query.
// Storing it in the URL keeps reloads and shared links on the same section.
import type { ParsedUrlQuery } from "querystring";

import { SETTINGS_NAV_ITEMS } from "./constants";
import type { SettingsSection } from "./page_types";

// セクションを保持するクエリパラメータ名
// Name of the query parameter that carries the section
export const SETTINGS_SECTION_QUERY_KEY = "section";

// クエリ未指定時に開くセクション
// Section opened when the query is absent
export const DEFAULT_SETTINGS_SECTION: SettingsSection = "profile";

// 未知の文字列を受け取り、サイドバーに存在するセクションだけを通す
// Accept an arbitrary string and let through only sections that exist in the sidebar
export function parseSettingsSection(value: unknown): SettingsSection | null {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (typeof candidate !== "string") return null;
  const match = SETTINGS_NAV_ITEMS.find((item) => item.section === candidate);
  return match ? match.section : null;
}

// 現在のクエリへセクションを反映した新しいクエリを作る。
// 既定セクションではパラメータを落とし、URL を余計に汚さない。
// Build a new query with the section applied. The default section drops the
// parameter so the URL stays clean.
export function buildSettingsSectionQuery(
  query: ParsedUrlQuery,
  section: SettingsSection
): ParsedUrlQuery {
  const nextQuery: ParsedUrlQuery = { ...query };
  if (section === DEFAULT_SETTINGS_SECTION) {
    delete nextQuery[SETTINGS_SECTION_QUERY_KEY];
    return nextQuery;
  }
  nextQuery[SETTINGS_SECTION_QUERY_KEY] = section;
  return nextQuery;
}

// URL の書き換えが必要か判定する — 同じ値での replace を避けて履歴操作を最小限にする
// Decide whether the URL needs rewriting — avoids replacing with an identical value
export function shouldSyncSettingsSectionUrl(
  query: ParsedUrlQuery,
  section: SettingsSection
): boolean {
  const current = parseSettingsSection(query[SETTINGS_SECTION_QUERY_KEY]);
  const hasParam = query[SETTINGS_SECTION_QUERY_KEY] !== undefined;
  if (section === DEFAULT_SETTINGS_SECTION) return hasParam;
  return current !== section;
}
