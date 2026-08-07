import assert from "node:assert/strict";
import test from "node:test";

import {
  SETTINGS_SECTION_QUERY_KEY,
  buildSettingsSectionQuery,
  parseSettingsSection,
  shouldSyncSettingsSectionUrl
} from "../scripts/user/settings/section_url";

test("parses only sections that exist in the settings sidebar", () => {
  assert.equal(parseSettingsSection("security"), "security");
  assert.equal(parseSettingsSection("liked-prompts"), "liked-prompts");
  assert.equal(parseSettingsSection("unknown-section"), null);
  assert.equal(parseSettingsSection(undefined), null);
  assert.equal(parseSettingsSection(["prompts", "security"]), "prompts");
});

test("writes the selected section into the query while keeping other parameters", () => {
  const query = buildSettingsSectionQuery({ ref: "mail" }, "prompts");

  assert.equal(query[SETTINGS_SECTION_QUERY_KEY], "prompts");
  assert.equal(query.ref, "mail");
});

test("drops the query parameter for the default section", () => {
  const query = buildSettingsSectionQuery({ section: "security", ref: "mail" }, "profile");

  assert.equal(SETTINGS_SECTION_QUERY_KEY in query, false);
  assert.equal(query.ref, "mail");
});

test("skips the URL rewrite when the query already matches the section", () => {
  assert.equal(shouldSyncSettingsSectionUrl({ section: "security" }, "security"), false);
  assert.equal(shouldSyncSettingsSectionUrl({}, "profile"), false);

  assert.equal(shouldSyncSettingsSectionUrl({ section: "security" }, "prompts"), true);
  assert.equal(shouldSyncSettingsSectionUrl({}, "security"), true);
  assert.equal(shouldSyncSettingsSectionUrl({ section: "security" }, "profile"), true);
});
