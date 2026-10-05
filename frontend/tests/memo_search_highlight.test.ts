import assert from "node:assert/strict";
import test from "node:test";

import { buildHighlightPattern, kanaVariants, splitByPattern, splitSearchTerms } from "../lib/memo/search_highlight";

const matches = (text: string, query: string) =>
  splitByPattern(text, buildHighlightPattern(query)).filter((part) => part.match).map((part) => part.text);

// バックエンド（services/search_terms.py）の分割規則と同じ結果になること
// Must split exactly like the backend (services/search_terms.py)
test("splits terms on whitespace and punctuation, dedupes, and caps at 8", () => {
  assert.deepEqual(splitSearchTerms("沖縄 旅行　予算"), ["沖縄", "旅行", "予算"]);
  assert.deepEqual(splitSearchTerms("a、b。a,c"), ["a", "b", "c"]);
  assert.deepEqual(splitSearchTerms("https://example.com/a_b"), ["https", "//example", "com/a_b"]);
  assert.equal(splitSearchTerms("1 2 3 4 5 6 7 8 9 10").length, 8);
  assert.deepEqual(splitSearchTerms("   "), []);
});

test("spells a term in hiragana and katakana, leaving ー and unpaired characters alone", () => {
  assert.deepEqual(kanaVariants("ぱすぽーと"), ["ぱすぽーと", "パスポート"]);
  assert.deepEqual(kanaVariants("パスポート"), ["パスポート", "ぱすぽーと"]);
  assert.deepEqual(kanaVariants("旅行"), ["旅行"]);
  assert.deepEqual(kanaVariants("ヷ"), ["ヷ"]);
});

test("matches hiragana and katakana alike", () => {
  assert.deepEqual(matches("持ち物: パスポート と 充電器", "ぱすぽーと"), ["パスポート"]);
  assert.deepEqual(matches("ぱすぽーとを探す", "パスポート"), ["ぱすぽーと"]);
});

test("ignores case without shifting positions", () => {
  assert.deepEqual(matches("Hello WORLD hello", "hello"), ["Hello", "hello"]);
  const parts = splitByPattern("Ab Cd", buildHighlightPattern("cd"));
  assert.deepEqual(parts, [{ text: "Ab ", match: false }, { text: "Cd", match: true }]);
});

test("takes the longer spelling when terms overlap", () => {
  assert.deepEqual(matches("パスポートを更新", "パス パスポート"), ["パスポート"]);
});

test("treats regex metacharacters in the query literally", () => {
  assert.deepEqual(matches("a+b と aab", "a+b"), ["a+b"]);
  assert.deepEqual(matches("x*y と xxy", "x*y"), ["x*y"]);
  assert.deepEqual(matches("1+1=2 と 11=2", "1+1"), ["1+1"]);
});

test("gives nothing to mark without a usable query", () => {
  assert.equal(buildHighlightPattern(""), null);
  assert.equal(buildHighlightPattern(" 、 "), null);
  assert.deepEqual(splitByPattern("そのまま", null), [{ text: "そのまま", match: false }]);
});
