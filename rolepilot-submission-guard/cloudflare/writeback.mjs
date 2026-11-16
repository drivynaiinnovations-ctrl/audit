// Runner result -> COI tracker write-back. Writes ONLY the three RolePilot prep columns of the one row whose
// Opportunity ID matches, after verifying the row's company/role identity. Never touches Status, Applied,
// Applied At, Application Authorization or any other column, and never records a submission.
//
// Row location is by Opportunity ID (re-read on every attempt), so sorting or moving rows is safe. Sheets has no
// compare-and-swap, so the ID is re-checked immediately before writing and the write is verified afterwards; if a
// sort landed in between, the cells written to the wrong row are restored from the pre-write snapshot and the
// attempt is retried.

import { identityKey } from "./coi.mjs";
import { RESULT_STATUSES } from "./prep.mjs";

export const TAB = "Opportunities";
export const WB = {
  status: "RolePilot Prep Status",
  at: "RolePilot Prep Updated At",
  result: "RolePilot Prep Result",
};
// Columns write-back must never touch (defence in depth; WB names are constants).
const PROTECTED = new Set(["Opportunity ID", "Company", "Role", "Status", "Applied", "Applied At / Follow-Up",
  "Application Authorization", "Package Status", "Conversion Stage", "Final Submission Permission", "Submission Evidence",
  "Outreach Sent At"]);

const text = (v) => String(v ?? "").trim();
const q = (t) => `'${t.replace(/'/g, "''")}'`;

export function columnLetter(index) { // 0-based
  let n = index + 1, s = "";
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

export const marker = (jobId) => `job=${jobId}`;

/** Cell values for one result. The status cell always says NOT SUBMITTED for a ready result. */
export function cellsFor(wb) {
  const r = wb.result;
  if (!RESULT_STATUSES.has(r.status) || r.submitted !== false || r.final_submit_clicked !== false) throw new Error("WRITEBACK_INVALID_RESULT");
  const parts = [r.status, `pages=${r.pages}`];
  if (r.attached?.length) parts.push(`attached=${r.attached.join(",")}`);
  if (wb.manifest_id) parts.push(`manifest=${wb.manifest_id}`);
  if (r.new_questions?.length) parts.push(`new questions (approve before retry): ${r.new_questions.join(" | ")}`);
  if (r.detail) parts.push(`detail=${r.detail}`);
  parts.push("submitted=false", marker(wb.job_id));
  return { status: "PREP " + r.status, at: wb.result_at, result: parts.join(" · ").slice(0, 1800) };
}

async function headerMap(sheets) {
  const [rows] = await sheets.get([`${q(TAB)}!1:1`]);
  const headers = (rows[0] || []).map(text);
  const idx = {};
  for (const h of ["Opportunity ID", "Company", "Role", WB.status, WB.at, WB.result]) {
    const at = headers.indexOf(h);
    if (at < 0) throw new Error(h.startsWith("RolePilot") ? "WRITEBACK_COLUMNS_MISSING" : "COI_SCHEMA_MISSING");
    if (headers.lastIndexOf(h) !== at) throw new Error("COI_HEADERS_NOT_UNIQUE");
    idx[h] = at;
  }
  for (const h of Object.values(WB)) if (PROTECTED.has(h)) throw new Error("WRITEBACK_PROTECTED_COLUMN");
  return { idx, width: headers.length };
}

async function snapshot(sheets, idx) {
  const names = ["Opportunity ID", "Company", "Role", WB.status, WB.at, WB.result];
  const cols = await sheets.get(names.map((h) => `${q(TAB)}!${columnLetter(idx[h])}:${columnLetter(idx[h])}`), "COLUMNS");
  const col = Object.fromEntries(names.map((h, i) => [h, cols[i][0] || []]));
  const rows = Math.max(...names.map((h) => col[h].length));
  const out = [];
  for (let i = 1; i < rows; i++) { // i = 0 is the header
    out.push({ row: i + 1, id: text(col["Opportunity ID"][i]), company: text(col.Company[i]), role: text(col.Role[i]),
      status: text(col[WB.status][i]), at: text(col[WB.at][i]), result: text(col[WB.result][i]) });
  }
  return out;
}

const cellRange = (idx, h, row) => `${q(TAB)}!${columnLetter(idx[h])}${row}`;
const writeData = (idx, row, cells) => [
  { range: cellRange(idx, WB.status, row), values: [[cells.status]] },
  { range: cellRange(idx, WB.at, row), values: [[cells.at]] },
  { range: cellRange(idx, WB.result, row), values: [[cells.result]] },
];

/**
 * Decide and (if appropriate) perform one write-back.
 * wb: { job_id, opportunity, identity, manifest_id, result, result_at }
 * lastWritten: { status, at } most recently written by RolePilot for this opportunity (from D1), or null.
 * Returns { state, row?, detail? }. Throws on retryable failures.
 */
export async function writeBack(sheets, wb, lastWritten) {
  const cells = cellsFor(wb);
  const { idx } = await headerMap(sheets);
  const before = await snapshot(sheets, idx);
  const matches = before.filter((r) => r.id === wb.opportunity);
  if (matches.length === 0) return { state: "HOLD_ROW_NOT_FOUND" };
  if (matches.length > 1) return { state: "HOLD_ROW_AMBIGUOUS", detail: matches.map((m) => m.row).join(",") };
  const target = matches[0];
  if (identityKey(target.company, target.role) !== wb.identity) return { state: "HOLD_ROW_IDENTITY_MISMATCH", row: target.row };

  // Idempotent retry: this exact result is already in the row.
  if (target.result.includes(marker(wb.job_id)) && target.status === cells.status && target.at === cells.at) {
    return { state: "WRITTEN", row: target.row, detail: "already present" };
  }
  // A newer value (from RolePilot or a person) is already there.
  if (target.at && target.at > cells.at) return { state: "SKIPPED_NEWER", row: target.row };
  // Manual edits win: a non-empty status RolePilot did not write is preserved.
  const ours = lastWritten && target.status === lastWritten.status && target.at === lastWritten.at;
  if ((target.status || target.at || target.result) && !ours) return { state: "SKIPPED_MANUAL", row: target.row };

  // Re-verify the row identity immediately before writing (narrows the sort window to one round trip).
  const [[recheck = []]] = await sheets.get([cellRange(idx, "Opportunity ID", target.row)]);
  if (text(recheck[0]) !== wb.opportunity) throw new Error("WRITEBACK_ROW_MOVED_RETRY");
  await sheets.update(writeData(idx, target.row, cells));

  // Verify: exactly one row carries this job's marker, and it is the right opportunity.
  const after = await snapshot(sheets, idx);
  const carrying = after.filter((r) => r.result.includes(marker(wb.job_id)));
  const wrong = carrying.filter((r) => r.id !== wb.opportunity);
  if (wrong.length) {
    const prior = new Map(before.map((r) => [r.id, r]));
    await sheets.update(wrong.flatMap((r) => {
      const p = prior.get(r.id) || { status: "", at: "", result: "" };
      return writeData(idx, r.row, p);
    }));
    throw new Error("WRITEBACK_ROW_MOVED_RETRY");
  }
  const landed = carrying.find((r) => r.id === wb.opportunity);
  if (!landed || landed.status !== cells.status || landed.at !== cells.at) throw new Error("WRITEBACK_VERIFY_FAILED_RETRY");
  return { state: "WRITTEN", row: landed.row };
}

/** Append the three write-back headers after the last header, if missing. Touches row 1 only. */
export async function ensureColumns(sheets) {
  const [rows] = await sheets.get([`${q(TAB)}!1:1`]);
  const headers = (rows[0] || []).map(text);
  if (!headers.includes("Opportunity ID")) throw new Error("COI_SCHEMA_MISSING");
  const missing = Object.values(WB).filter((h) => !headers.includes(h));
  if (!missing.length) return { added: [], columns: Object.values(WB).map((h) => columnLetter(headers.indexOf(h))) };
  const start = headers.length;
  if (sheets.ensureColumnCount) await sheets.ensureColumnCount(TAB, start + missing.length);
  await sheets.update([{ range: `${q(TAB)}!${columnLetter(start)}1:${columnLetter(start + missing.length - 1)}1`, values: [missing] }]);
  const all = [...headers, ...missing];
  return { added: missing, columns: Object.values(WB).map((h) => columnLetter(all.indexOf(h))) };
}

/** Read back the three cells (plus identity) for an opportunity, for verification. */
export async function readBack(sheets, opportunity) {
  const { idx } = await headerMap(sheets);
  const rows = (await snapshot(sheets, idx)).filter((r) => r.id === opportunity);
  return rows.map((r) => ({ row: r.row, company: r.company, role: r.role, status: r.status, at: r.at, result: r.result }));
}
