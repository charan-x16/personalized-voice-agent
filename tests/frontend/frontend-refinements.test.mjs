import assert from "node:assert/strict";
import test from "node:test";
import { conversationPage, conversationArchiveHref } from "../../src/lib/conversation-query.ts";
import { isNearTranscriptBottom } from "../../src/lib/voice/transcript-scroll.ts";
import {
  INDIAN_LANGUAGE_COUNT,
  SELECTABLE_LANGUAGES,
  SUPPORTED_LANGUAGES,
  supportedLanguageByCode,
} from "../../src/lib/languages.ts";

test("archive pagination rejects ambiguous and unbounded page parameters", () => {
  assert.equal(conversationPage(undefined), 1);
  assert.equal(conversationPage("501"), 501);
  for (const value of ["0", "-1", "01", "1.5", "1e2", "502", "", "Infinity"]) {
    assert.equal(conversationPage(value), null);
  }
});

test("archive links preserve encoded search and outcome across pages", () => {
  assert.equal(conversationArchiveHref("", "all"), "/conversations");
  const url = new URL(conversationArchiveHref("plan & invoice", "follow-up", 3), "https://example.test");
  assert.equal(url.searchParams.get("query"), "plan & invoice");
  assert.equal(url.searchParams.get("outcome"), "follow-up");
  assert.equal(url.searchParams.get("page"), "3");
  assert.ok(!conversationArchiveHref("plan", "resolved").includes("page="));
});

test("transcript follows new messages only when near the bottom", () => {
  assert.equal(isNearTranscriptBottom(0, 200, 260), true);
  assert.equal(isNearTranscriptBottom(700, 1000, 260), true);
  assert.equal(isNearTranscriptBottom(100, 1000, 260), false);
  assert.equal(isNearTranscriptBottom(739.5, 1000, 260), true);
});

test("the shared language catalogue matches the supported Voice Agents surface", () => {
  assert.equal(INDIAN_LANGUAGE_COUNT, 11);
  assert.equal(SUPPORTED_LANGUAGES.length, 12);
  assert.equal(SELECTABLE_LANGUAGES.length, 12);
  assert.equal(new Set(SUPPORTED_LANGUAGES.map((language) => language.code)).size, 12);
  assert.equal(supportedLanguageByCode("hi")?.nativeName, "हिन्दी");
  assert.equal(supportedLanguageByCode("kok"), undefined);
});
