// Run with: node --test feedback.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const {
    FEEDBACK_ERROR_MAX_LENGTH,
    FEEDBACK_USER_AGENT_MAX_LENGTH,
    truncateText,
    formatLocalDateTime,
    describeStage,
    operationLabel,
    isFeedbackConfigured,
    composeErrorText,
    buildFeedbackUrl,
} = require("./static/feedback.js");

const FULL_CONFIG = {
    url: "https://docs.google.com/forms/d/e/FORM/viewform",
    entries: {
        operation: "entry.1", version: "entry.2", stage: "entry.3",
        error: "entry.4", userAgent: "entry.5", datetime: "entry.6",
    },
};

const CONFIG = {
    url: "https://docs.google.com/forms/d/e/FORM/viewform",
    entries: { version: "entry.1", error: "entry.2", operation: "entry.3" },
};

test("buildFeedbackUrl: adds usp=pp_url and encodes values", () => {
    const url = new URL(buildFeedbackUrl(CONFIG, {
        version: "1.5.0",
        error: "失敗 & retry?=1#x",
        operation: "シフト作成",
    }));
    assert.equal(url.origin + url.pathname, CONFIG.url);
    assert.equal(url.hash, "");
    assert.equal(url.searchParams.get("usp"), "pp_url");
    assert.equal(url.searchParams.get("entry.1"), "1.5.0");
    assert.equal(url.searchParams.get("entry.2"), "失敗 & retry?=1#x");
    assert.equal(url.searchParams.get("entry.3"), "シフト作成");
});

test("buildFeedbackUrl: skips empty values, missing values and fields without entry ID", () => {
    const config = { url: CONFIG.url, entries: { version: "entry.1", error: "entry.2", stage: "", operation: "entry.3" } };
    const url = new URL(buildFeedbackUrl(config, { version: "1.5.0", error: "", stage: "x", operation: null }));
    assert.deepEqual([...url.searchParams.keys()], ["usp", "entry.1"]);
});

test("buildFeedbackUrl: ignores values with no configured entry", () => {
    const url = new URL(buildFeedbackUrl(CONFIG, { version: "1", unknown: "secret" }));
    assert.equal(url.search.includes("secret"), false);
});

test("isFeedbackConfigured: false until the URL and every entry ID are set", () => {
    assert.equal(isFeedbackConfigured({ url: "", entries: { version: "" } }), false);
    assert.equal(isFeedbackConfigured({ url: CONFIG.url, entries: { version: "", error: "" } }), false);
    assert.equal(isFeedbackConfigured({ url: "", entries: { version: "entry.1" } }), false);
    assert.equal(isFeedbackConfigured({ url: CONFIG.url, entries: {} }), false);
    assert.equal(isFeedbackConfigured({ url: CONFIG.url }), false);
    assert.equal(isFeedbackConfigured(null), false);
    assert.equal(isFeedbackConfigured(FULL_CONFIG), true);
});

test("isFeedbackConfigured: a missing field keeps the link hidden", () => {
    assert.equal(isFeedbackConfigured(CONFIG), false);
    const { datetime, ...withoutDatetime } = FULL_CONFIG.entries;
    assert.equal(isFeedbackConfigured({ url: FULL_CONFIG.url, entries: withoutDatetime }), false);
    // Extra keys do not matter
    assert.equal(isFeedbackConfigured({ url: FULL_CONFIG.url, entries: { ...FULL_CONFIG.entries, extra: "" } }), true);
});

test("composeErrorText: joins the alert and the warnings on screen, skipping empties", () => {
    assert.equal(composeErrorText("", []), "");
    assert.equal(composeErrorText("", null), "");
    assert.equal(composeErrorText("失敗", []), "失敗");
    assert.equal(composeErrorText("", ["警告1", "警告2"]), "警告1 警告2");
    assert.equal(composeErrorText("失敗", ["", "警告"]), "失敗 警告");
});

test("isFeedbackConfigured: a partly filled config keeps the link hidden", () => {
    const partial = { url: CONFIG.url, entries: { version: "entry.1", error: "", operation: "entry.3" } };
    assert.equal(isFeedbackConfigured(partial), false);
});

test("isFeedbackConfigured: rejects non-form URLs and malformed entry IDs", () => {
    assert.equal(isFeedbackConfigured({ url: "https://example.com/form", entries: CONFIG.entries }), false);
    assert.equal(isFeedbackConfigured({ url: "javascript:alert(1)", entries: CONFIG.entries }), false);
    assert.equal(isFeedbackConfigured({ url: CONFIG.url, entries: { ...FULL_CONFIG.entries, version: "1234" } }), false);
    assert.equal(isFeedbackConfigured({ url: CONFIG.url, entries: { ...FULL_CONFIG.entries, version: "entry.abc" } }), false);
    assert.equal(isFeedbackConfigured({ url: "https://example.com/form", entries: FULL_CONFIG.entries }), false);
});

test("truncateText: keeps short text, cuts long text at the limit", () => {
    assert.equal(truncateText("abc", 3), "abc");
    assert.equal(truncateText("abcd", 3), "ab…");
    assert.equal(truncateText("", 3), "");
    assert.equal(truncateText(null, 3), "");
    assert.equal(truncateText(undefined, 3), "");
});

test("truncateText: does not split surrogate pairs", () => {
    assert.equal(truncateText("😀😀😀", 2), "😀…");
});

test("truncateText: result including the ellipsis never exceeds the limit", () => {
    const cut = truncateText("エ".repeat(5000), FEEDBACK_ERROR_MAX_LENGTH);
    assert.equal(Array.from(cut).length, FEEDBACK_ERROR_MAX_LENGTH);
    assert.ok(cut.endsWith("…"));
    const exact = "エ".repeat(FEEDBACK_ERROR_MAX_LENGTH);
    assert.equal(truncateText(exact, FEEDBACK_ERROR_MAX_LENGTH), exact);
});

test("worst case: long non-ASCII error and User-Agent keep the URL within a safe length", () => {
    const config = {
        url: CONFIG.url,
        entries: { version: "entry.1", stage: "entry.2", error: "entry.3", userAgent: "entry.4", datetime: "entry.5", operation: "entry.6" },
    };
    const url = buildFeedbackUrl(config, {
        version: "1.5.0",
        stage: describeStage({ hasUpload: true, hasGenerated: true, isLoading: true }),
        error: truncateText("エ".repeat(5000), FEEDBACK_ERROR_MAX_LENGTH),
        userAgent: truncateText("ブ".repeat(5000), FEEDBACK_USER_AGENT_MAX_LENGTH),
        datetime: "2026-10-27 22:00:00",
        operation: "設定・プリセット",
    });
    // Google Forms pre-filled links work well below ~8000 characters
    assert.ok(url.length < 8000, `url length ${url.length}`);
});

test("long error keeps the whole URL within a safe length", () => {
    const config = {
        url: CONFIG.url,
        entries: { version: "entry.1", stage: "entry.2", error: "entry.3", userAgent: "entry.4", datetime: "entry.5", operation: "entry.6" },
    };
    const url = buildFeedbackUrl(config, {
        version: "1.5.0",
        stage: describeStage({ hasUpload: true, hasGenerated: true, isLoading: true }),
        error: truncateText("エ".repeat(5000), FEEDBACK_ERROR_MAX_LENGTH),
        userAgent: "Mozilla/5.0 ".repeat(20),
        datetime: "2026-10-27 22:00:00",
        operation: "再作成",
    });
    assert.ok(url.length < 4000, `url length ${url.length}`);
});

test("formatLocalDateTime: zero-pads local date and time", () => {
    assert.equal(formatLocalDateTime(new Date(2026, 0, 2, 3, 4, 5)), "2026-01-02 03:04:05");
    assert.equal(formatLocalDateTime(new Date(2026, 11, 31, 23, 59, 59)), "2026-12-31 23:59:59");
});

test("describeStage: covers each stage", () => {
    assert.equal(describeStage({ hasUpload: false, hasGenerated: false, isLoading: false }), "ファイル未アップロード");
    assert.equal(describeStage({ hasUpload: false, hasGenerated: false, isLoading: true }), "ファイル未アップロード（処理中）");
    assert.equal(describeStage({ hasUpload: true, hasGenerated: false, isLoading: false }), "ファイル読み込み済み（シフト未作成）");
    assert.equal(describeStage({ hasUpload: true, hasGenerated: true, isLoading: false }), "シフト作成済み");
    assert.equal(describeStage({ hasUpload: true, hasGenerated: true, isLoading: true }), "シフト作成済み（処理中）");
});

test("operationLabel: maps known keys to form choices, unknown to empty", () => {
    assert.equal(operationLabel("upload"), "ファイルのアップロード");
    assert.equal(operationLabel("generate"), "シフト作成");
    assert.equal(operationLabel("regenerate"), "再作成");
    assert.equal(operationLabel("download"), "ダウンロード");
    assert.equal(operationLabel("settings"), "設定・プリセット");
    assert.equal(operationLabel(null), "");
    assert.equal(operationLabel(undefined), "");
    assert.equal(operationLabel("toString"), "");
});
