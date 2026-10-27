/**
 * Pure helpers for the "うまくいかなかったときはこちら" feedback link.
 * Loaded as a classic script before app.js; also loadable from Node for tests.
 */

const FEEDBACK_ERROR_MAX_LENGTH = 300;
const FEEDBACK_USER_AGENT_MAX_LENGTH = 300;
const FEEDBACK_FORM_URL_PREFIX = "https://docs.google.com/forms/";

// Operation keys recorded by app.js -> choice labels on the Google Form
// (the form also has "その他", which the app never pre-fills)
const FEEDBACK_OPERATION_LABELS = {
    upload: "ファイルのアップロード",
    generate: "シフト作成",
    regenerate: "再作成",
    download: "ダウンロード",
    settings: "設定・プリセット",
};

function truncateText(text, maxLength) {
    const s = (text || "").toString();
    // Array.from counts code points so a surrogate pair is never split
    const chars = Array.from(s);
    if (chars.length <= maxLength) return s;
    // Keep the result within maxLength including the ellipsis
    return chars.slice(0, maxLength - 1).join("") + "…";
}

function formatLocalDateTime(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
        + `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function describeStage({ hasUpload, hasGenerated, isLoading }) {
    let stage;
    if (!hasUpload) stage = "ファイル未アップロード";
    else if (hasGenerated) stage = "シフト作成済み";
    else stage = "ファイル読み込み済み（シフト未作成）";
    if (isLoading) stage += "（処理中）";
    return stage;
}

function operationLabel(operationKey) {
    return Object.hasOwn(FEEDBACK_OPERATION_LABELS, operationKey ?? "")
        ? FEEDBACK_OPERATION_LABELS[operationKey]
        : "";
}

// The link is shown only after the form URL and every entry ID are filled in
function isFeedbackConfigured(config) {
    if (!config || typeof config.url !== "string" || !config.url.startsWith(FEEDBACK_FORM_URL_PREFIX)) return false;
    const entryIds = Object.values(config.entries || {});
    return entryIds.length > 0 && entryIds.every((id) => /^entry\.\d+$/.test(id));
}

/**
 * Build a pre-filled Google Form URL.
 * config: { url, entries: { <field>: "entry.<ID>" } }
 * values: { <field>: string } — empty values and fields without an entry ID are skipped.
 */
function buildFeedbackUrl(config, values) {
    const params = new URLSearchParams();
    params.set("usp", "pp_url");
    for (const [field, entryId] of Object.entries(config.entries)) {
        const value = values[field];
        if (!entryId || value === undefined || value === null || value === "") continue;
        params.append(entryId, String(value));
    }
    return `${config.url}?${params.toString()}`;
}

if (typeof module !== "undefined") {
    module.exports = {
        FEEDBACK_ERROR_MAX_LENGTH,
        FEEDBACK_USER_AGENT_MAX_LENGTH,
        FEEDBACK_OPERATION_LABELS,
        truncateText,
        formatLocalDateTime,
        describeStage,
        operationLabel,
        isFeedbackConfigured,
        buildFeedbackUrl,
    };
}
