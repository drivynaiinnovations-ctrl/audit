// Write-back tests: real SQLite (node:sqlite) running schema.sql as a D1 stand-in, and an in-memory spreadsheet
// that supports the ranges the Worker uses. All data is synthetic.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { writeBack, ensureColumns, columnLetter, WB, readBack } from "./writeback.mjs";
import { importAndEnqueue, consume, claim, complete, processWriteback, sweepWritebacks } from "./prep.mjs";
import { seedSynthetic, syntheticPage, syntheticEvent } from "./synthetic.mjs";
import { identityKey } from "./coi.mjs";
import worker from "./index.mjs";

// ------------------------------------------------------------------ D1 shim
function d1() {
  const db = new DatabaseSync(":memory:");
  // Guard table as it exists in the live D1 (created before schema.sql); copied from sqlite_master.
  db.exec("CREATE TABLE submission_reservations (id INTEGER PRIMARY KEY, opportunity TEXT UNIQUE NOT NULL, employer TEXT NOT NULL, " +
    "role TEXT NOT NULL, requisition TEXT NOT NULL, url TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'RESERVED', created_at TEXT DEFAULT CURRENT_TIMESTAMP)");
  db.exec(readFileSync(new URL("./schema.sql", import.meta.url), "utf8"));
  const stmt = (sql, args = []) => ({
    bind: (...a) => stmt(sql, a),
    first: async () => db.prepare(sql).get(...args) ?? null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    run: async () => { const r = db.prepare(sql).run(...args); return { meta: { changes: Number(r.changes) } }; },
  });
  return { prepare: (sql) => stmt(sql), batch: async (s) => Promise.all(s.map((x) => x.run())), raw: db };
}

// ------------------------------------------------------------------ fake spreadsheet
const colIndex = (letters) => [...letters].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0) - 1;
class Sheet {
  constructor(tabs) {
    this.tabs = tabs; this.updates = 0; this.beforeUpdate = null;
    // Like Google Sheets, a values write outside the grid is rejected; the grid starts as wide as row 1.
    this.grid = Object.fromEntries(Object.entries(tabs).map(([k, v]) => [k, Math.max(...v.map((r) => r.length))]));
  }
  async ensureColumnCount(name, n) { const added = Math.max(0, n - this.grid[name]); this.grid[name] += added; return { added }; }
  parse(range) {
    const m = range.match(/^'((?:[^']|'')+)'!(.+)$/);
    const tab = this.tabs[m[1].replace(/''/g, "'")];
    const ref = m[2];
    let r;
    if ((r = ref.match(/^(\d+):(\d+)$/))) return { tab, r0: +r[1] - 1, r1: +r[2] - 1, c0: 0, c1: 400 };
    if ((r = ref.match(/^([A-Z]+):([A-Z]+)$/))) return { tab, r0: 0, r1: 1e6, c0: colIndex(r[1]), c1: colIndex(r[2]) };
    if ((r = ref.match(/^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/))) {
      return { tab, r0: +r[2] - 1, r1: +(r[4] || r[2]) - 1, c0: colIndex(r[1]), c1: colIndex(r[3] || r[1]) };
    }
    throw new Error("bad range " + range);
  }
  async get(ranges, dim = "ROWS") {
    return ranges.map((range) => {
      const { tab, r0, r1, c0, c1 } = this.parse(range);
      const rows = [];
      for (let r = r0; r <= Math.min(r1, tab.length - 1); r++) {
        const row = [];
        for (let c = c0; c <= Math.min(c1, (tab[r] || []).length - 1); c++) row.push(tab[r][c] ?? "");
        while (row.length && row[row.length - 1] === "") row.pop();
        rows.push(row);
      }
      while (rows.length && rows[rows.length - 1].length === 0) rows.pop();
      if (dim === "ROWS") return rows;
      const width = Math.max(0, ...rows.map((x) => x.length));
      return Array.from({ length: width }, (_, c) => rows.map((x) => x[c] ?? ""));
    });
  }
  async update(data) {
    if (this.beforeUpdate) { const f = this.beforeUpdate; this.beforeUpdate = null; f(this); }
    this.updates++;
    for (const { range, values } of data) {
      const { tab, r0, c0 } = this.parse(range);
      const name = Object.keys(this.tabs).find((k) => this.tabs[k] === tab);
      if (c0 + Math.max(...values.map((r) => r.length)) > this.grid[name]) throw new Error("COI_SHEETS_FAILED_400_INVALID_ARGUMENT");
      values.forEach((row, i) => row.forEach((v, j) => { while (tab.length <= r0 + i) tab.push([]); tab[r0 + i][c0 + j] = v; }));
    }
  }
  async append(name, row) { this.tabs[name].push(row); }
}

const HEAD = ["Opportunity ID", "Company", "Role", "Direct Source URL", "Status", "Applied", "Application Authorization", "Notes"];
const MHEAD = ["Manifest ID", "Opportunity ID", "Approved Resume", "Approved Cover Letter", "Cover Letter Required", "Approved Screening Answers"];
const R = "https://drive.google.com/file/d/SYNTHRESUME0001/view";
const C = "https://docs.google.com/document/d/SYNTHCOVER00001/edit";
const row = (id, company) => [id, company, "Analyst", `https://jobs.example.test/${id}`, "Ready", "FALSE", "Authorized", ""];

function sheetWith(rows, { columns = true } = {}) {
  const head = columns ? [...HEAD, WB.status, WB.at, WB.result] : [...HEAD];
  return new Sheet({ Opportunities: [head, ...rows.map((r) => [...r])], "Application Manifests": [MHEAD,
    ...rows.map((r) => [`M-${r[0]}`, r[0], R, C, "Yes", ""])] });
}
const cell = (sheet, id, h) => {
  const t = sheet.tabs.Opportunities; const c = t[0].indexOf(h);
  return t.find((r) => r[0] === id)?.[c] ?? "";
};
const RESULT = { status: "READY_FOR_REVIEW_NOT_SUBMITTED", pages: 3, submitted: false, final_submit_clicked: false,
  new_questions: [], attached: ["cover_letter", "resume"], detail: "" };
const wbFor = (id, company, extra = {}) => ({ job_id: "job-" + id, opportunity: id, identity: identityKey(company, "Analyst"),
  manifest_id: "M-" + id, result: RESULT, result_at: "2026-11-16T12:00:00.000Z", ...extra });

// ------------------------------------------------------------------ writeBack unit tests
test("writes only the three prep cells of the matching row and never marks it submitted", async () => {
  const s = sheetWith([row("RP-1", "Acme"), row("RP-2", "Beta")]);
  const before = JSON.parse(JSON.stringify(s.tabs.Opportunities));
  const out = await writeBack(s, wbFor("RP-2", "Beta"), null);
  assert.equal(out.state, "WRITTEN");
  assert.equal(out.row, 3);
  assert.equal(cell(s, "RP-2", WB.status), "PREP READY_FOR_REVIEW_NOT_SUBMITTED");
  assert.match(cell(s, "RP-2", WB.result), /submitted=false/);
  assert.match(cell(s, "RP-2", WB.result), /attached=cover_letter,resume/);
  assert.match(cell(s, "RP-2", WB.result), /manifest=M-RP-2/);
  const after = s.tabs.Opportunities;
  for (let r = 0; r < before.length; r++) {
    for (let c = 0; c < HEAD.length; c++) assert.equal(after[r][c], before[r][c], `cell ${r},${c} untouched`);
  }
  assert.equal(cell(s, "RP-1", WB.status), "", "other rows untouched");
  assert.equal(cell(s, "RP-2", "Applied"), "FALSE");
  assert.equal(cell(s, "RP-2", "Status"), "Ready");
});

test("finds the row by Opportunity ID after the sheet is sorted", async () => {
  const s = sheetWith([row("RP-1", "Acme"), row("RP-2", "Beta"), row("RP-3", "Gamma")]);
  const [head, ...rows] = s.tabs.Opportunities;
  s.tabs.Opportunities = [head, ...rows.reverse()];
  const out = await writeBack(s, wbFor("RP-1", "Acme"), null);
  assert.equal(out.row, 4);
  assert.equal(cell(s, "RP-1", WB.status), "PREP READY_FOR_REVIEW_NOT_SUBMITTED");
  assert.equal(cell(s, "RP-3", WB.status), "");
});

test("a sort between the identity check and the write is detected, repaired and retried", async () => {
  const s = sheetWith([row("RP-1", "Acme"), row("RP-2", "Beta")]);
  s.tabs.Opportunities[2][HEAD.length] = "kept status"; // RP-2 has a manual value that must survive
  s.beforeUpdate = (sh) => { const t = sh.tabs.Opportunities; [t[1], t[2]] = [t[2], t[1]]; }; // sort lands mid-write
  await assert.rejects(writeBack(s, wbFor("RP-1", "Acme"), null), /WRITEBACK_ROW_MOVED_RETRY/);
  assert.equal(cell(s, "RP-2", WB.status), "kept status", "wrong row restored");
  assert.equal(cell(s, "RP-2", WB.result), "");
  const retry = await writeBack(s, wbFor("RP-1", "Acme"), null);
  assert.equal(retry.state, "WRITTEN");
  assert.equal(cell(s, "RP-1", WB.status), "PREP READY_FOR_REVIEW_NOT_SUBMITTED");
});

test("identity mismatch, duplicate IDs, missing row and missing columns all fail closed", async () => {
  const s = sheetWith([row("RP-1", "Acme")]);
  assert.equal((await writeBack(s, wbFor("RP-1", "Other Co"), null)).state, "HOLD_ROW_IDENTITY_MISMATCH");
  assert.equal((await writeBack(s, wbFor("RP-9", "Acme"), null)).state, "HOLD_ROW_NOT_FOUND");
  const d = sheetWith([row("RP-1", "Acme"), row("RP-1", "Acme")]);
  assert.equal((await writeBack(d, wbFor("RP-1", "Acme"), null)).state, "HOLD_ROW_AMBIGUOUS");
  await assert.rejects(writeBack(sheetWith([row("RP-1", "Acme")], { columns: false }), wbFor("RP-1", "Acme"), null), /WRITEBACK_COLUMNS_MISSING/);
  assert.equal(s.updates, 0);
});

test("manual and newer values are preserved; RolePilot's own older value is replaced", async () => {
  const s = sheetWith([row("RP-1", "Acme")]);
  const c = HEAD.length;
  s.tabs.Opportunities[1][c] = "Interviewing - set by hand";
  assert.equal((await writeBack(s, wbFor("RP-1", "Acme"), null)).state, "SKIPPED_MANUAL");
  s.tabs.Opportunities[1][c + 1] = "2026-12-01T00:00:00.000Z";
  assert.equal((await writeBack(s, wbFor("RP-1", "Acme"), null)).state, "SKIPPED_NEWER");
  assert.equal(cell(s, "RP-1", WB.status), "Interviewing - set by hand");

  const t = sheetWith([row("RP-1", "Acme")]);
  await writeBack(t, wbFor("RP-1", "Acme", { job_id: "old", result: { ...RESULT, status: "HOLD_CAPTCHA" }, result_at: "2026-11-15T00:00:00.000Z" }), null);
  const last = { status: "PREP HOLD_CAPTCHA", at: "2026-11-15T00:00:00.000Z" };
  assert.equal((await writeBack(t, wbFor("RP-1", "Acme"), last)).state, "WRITTEN");
  assert.equal(cell(t, "RP-1", WB.status), "PREP READY_FOR_REVIEW_NOT_SUBMITTED");
  // ...but an older result arriving late does not overwrite the newer one.
  const late = wbFor("RP-1", "Acme", { job_id: "late", result_at: "2026-11-14T00:00:00.000Z" });
  assert.equal((await writeBack(t, late, { status: "PREP READY_FOR_REVIEW_NOT_SUBMITTED", at: "2026-11-16T12:00:00.000Z" })).state, "SKIPPED_NEWER");
});

test("a repeated write-back of the same result performs no second update", async () => {
  const s = sheetWith([row("RP-1", "Acme")]);
  await writeBack(s, wbFor("RP-1", "Acme"), null);
  const n = s.updates;
  const again = await writeBack(s, wbFor("RP-1", "Acme"), null);
  assert.equal(again.state, "WRITTEN");
  assert.equal(s.updates, n);
});

test("write-back refuses a result that claims a submission", async () => {
  const s = sheetWith([row("RP-1", "Acme")]);
  await assert.rejects(writeBack(s, wbFor("RP-1", "Acme", { result: { ...RESULT, submitted: true } }), null), /WRITEBACK_INVALID_RESULT/);
  assert.equal(s.updates, 0);
});

test("ensureColumns appends the three headers once, touching row 1 only", async () => {
  const s = sheetWith([row("RP-1", "Acme")], { columns: false });
  const first = await ensureColumns(s);
  assert.deepEqual(first.added, Object.values(WB));
  assert.deepEqual(first.columns, [columnLetter(HEAD.length), columnLetter(HEAD.length + 1), columnLetter(HEAD.length + 2)]);
  assert.deepEqual((await ensureColumns(s)).added, []);
  assert.deepEqual(s.tabs.Opportunities[1], row("RP-1", "Acme"));
});

// ------------------------------------------------------------------ pipeline (D1 + queue) tests
function pipelineEnv(sheet, scope) {
  const sent = [];
  const env = { DB: d1(), PREP_QUEUE: { send: async (m) => { sent.push(m); } }, PREP_IMPORT_SCOPE: scope, COI_SHEET_ID: "test" };
  return { env, sent, sheet };
}
const deliver = async (env, messages) => {
  const acked = [];
  await consume({ messages: messages.map((body) => ({ body, attempts: 1, ack: () => acked.push(body), retry: () => {} })) }, env);
  return acked;
};

test("full pipeline: import -> queue -> D1 -> claim -> complete -> write-back; retries create no duplicates", async () => {
  const id = "RP-SYNTH-20261116-01";
  const sheet = sheetWith([row(id, "Synth Co"), row("REAL-1", "Real Co")]);
  const { env, sent } = pipelineEnv(sheet, undefined);
  const source = { opportunities: await sheet.get(["'Opportunities'!1:100"]).then((x) => x[0]),
    manifests: sheet.tabs["Application Manifests"] };
  const { evaluateCOI } = await import("./coi.mjs");
  const ev = evaluateCOI(source.opportunities, source.manifests);
  assert.deepEqual(ev.eligible.map((e) => e.opportunity_id).sort(), [id, "REAL-1"].sort());

  // Live import with the gate (scope unset => synthetic only).
  const imp = await importAndEnqueueWith(env, source);
  assert.deepEqual(imp.queued, [id]);
  assert.equal(imp.blocked.find((b) => b.opportunity_id === "REAL-1").reason, "HOLD_LIVE_IMPORT_NOT_ENABLED");
  const again = await importAndEnqueueWith(env, source);
  assert.deepEqual(again.queued, []);
  assert.equal(again.blocked.find((b) => b.opportunity_id === id).reason, "BLOCK_ALREADY_QUEUED");

  await deliver(env, [sent[0], sent[0]]); // duplicate queue delivery
  assert.equal((await env.DB.prepare("SELECT count(*) n FROM prep_jobs").first()).n, 1);

  const job = await claim(env);
  assert.equal(job.job.opportunity_id, id);
  const done = await complete(env, { job_id: job.id, result: RESULT });
  assert.equal(done.status, 200);
  assert.equal(done.body.writeback, "PENDING");
  const retryComplete = await complete(env, { job_id: job.id, result: RESULT });
  assert.equal(retryComplete.body.duplicate, true);
  assert.equal((await env.DB.prepare("SELECT count(*) n FROM prep_writeback").first()).n, 1);
  const wbMessages = sent.filter((m) => m.kind === "writeback");
  assert.equal(wbMessages.length, 1);

  const w1 = await processWriteback(env, job.id, sheet);
  assert.equal(w1.state, "WRITTEN");
  const updates = sheet.updates;
  const w2 = await processWriteback(env, job.id, sheet); // queue redelivery
  assert.equal(w2.state, "WRITTEN");
  assert.equal(sheet.updates, updates, "no duplicate sheet update");
  const back = await readBack(sheet, id);
  assert.equal(back.length, 1);
  assert.equal(back[0].status, "PREP READY_FOR_REVIEW_NOT_SUBMITTED");
  assert.match(back[0].result, new RegExp("job=" + job.id));
  assert.equal(cell(sheet, id, "Applied"), "FALSE");
  assert.equal(cell(sheet, "REAL-1", WB.status), "");
  assert.deepEqual(await sweepWritebacks(env), []);
});

test("transient Sheets failures are retried and then recorded", async () => {
  const id = "RP-SYNTH-20261116-02";
  const sheet = sheetWith([row(id, "Synth Co")]);
  const { env, sent } = pipelineEnv(sheet, undefined);
  await importAndEnqueueWith(env, { opportunities: sheet.tabs.Opportunities, manifests: sheet.tabs["Application Manifests"] });
  await deliver(env, sent.splice(0));
  const job = await claim(env);
  await complete(env, { job_id: job.id, result: RESULT });
  const flaky = { get: async () => { throw new Error("COI_SHEETS_RETRYABLE_503"); } };
  const r = await processWriteback(env, job.id, flaky);
  assert.deepEqual([r.state, r.retry, r.detail], ["RETRY", true, "COI_SHEETS_RETRYABLE_503"]);
  assert.equal((await processWriteback(env, job.id, sheet)).state, "WRITTEN");
});

test("a runner result claiming submission is rejected and never written back", async () => {
  const id = "RP-SYNTH-20261116-03";
  const sheet = sheetWith([row(id, "Synth Co")]);
  const { env, sent } = pipelineEnv(sheet, undefined);
  await importAndEnqueueWith(env, { opportunities: sheet.tabs.Opportunities, manifests: sheet.tabs["Application Manifests"] });
  await deliver(env, sent.splice(0));
  const job = await claim(env);
  const r = await complete(env, { job_id: job.id, result: { ...RESULT, submitted: true, final_submit_clicked: true } });
  assert.equal(r.body.reason, "SUBMISSION_VIOLATION");
  assert.equal((await env.DB.prepare("SELECT count(*) n FROM prep_writeback").first()).n, 0);
  assert.equal(sheet.updates, 0);
  assert.equal((await complete(env, { job_id: job.id, result: { ...RESULT, attached: ["passport"] } })).body.reason, "LEASE_NOT_HELD");
});

test("PREP_IMPORT_SCOPE=all queues real authorized rows", async () => {
  const sheet = sheetWith([row("REAL-1", "Real Co")]);
  const { env } = pipelineEnv(sheet, "all");
  const r = await importAndEnqueueWith(env, { opportunities: sheet.tabs.Opportunities, manifests: sheet.tabs["Application Manifests"] });
  assert.deepEqual(r.queued, ["REAL-1"]);
});

// importAndEnqueue reads the live sheet when audit=false; route that read to the fixture for tests.
async function importAndEnqueueWith(env, source) {
  const saved = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("network disabled in tests"); };
  try {
    return await importAndEnqueue(env, { audit: false, sheetValues: source });
  } finally { globalThis.fetch = saved; }
}

// ------------------------------------------------------------------ synthetic role
test("synthetic seed appends one labeled row per tab, idempotently, never marked applied", async () => {
  const s = sheetWith([row("REAL-1", "Real Co")]);
  const args = { id: "RP-SYNTH-20261116-01", origin: "https://w.example", resume: R, cover: C };
  const first = await seedSynthetic(s, args);
  assert.deepEqual([first.opportunity_added, first.manifest_added], [true, true]);
  const again = await seedSynthetic(s, args);
  assert.deepEqual([again.opportunity_added, again.manifest_added], [false, false]);
  const o = s.tabs.Opportunities;
  assert.equal(o.length, 3);
  const added = o[2];
  assert.equal(added[HEAD.indexOf("Applied")], "FALSE");
  assert.match(added[HEAD.indexOf("Company")], /NOT A REAL EMPLOYER/);
  assert.equal(added[HEAD.indexOf("Direct Source URL")], "https://w.example/synthetic/apply/RP-SYNTH-20261116-01");
  await assert.rejects(seedSynthetic(s, { ...args, id: "REAL-2" }), /SYNTHETIC_ID_INVALID/);
  await assert.rejects(seedSynthetic(s, { ...args, id: "RP-SYNTH-20261116-02", resume: "https://evil.example/x" }), /DRIVE/);
});

test("synthetic form is served only for synthetic IDs and a final click is recorded as a violation", async () => {
  const env = { DB: d1() };
  const page = await worker.fetch(new Request("https://w.example/synthetic/apply/RP-SYNTH-20261116-01"), env);
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.match(html, /Submit Application/);
  assert.match(html, /NOT A REAL EMPLOYER/);
  assert.equal((await worker.fetch(new Request("https://w.example/synthetic/apply/REAL-1"), env)).status, 404);
  assert.equal(await syntheticEvent(env, "final", { id: "RP-SYNTH-20261116-01" }), true);
  assert.equal((await env.DB.prepare("SELECT count(*) n FROM prep_events WHERE event='SUBMISSION_VIOLATION'").first()).n, 1);
  assert.match(syntheticPage("RP-SYNTH-20261116-01"), /Apply/);
});

test("operator write-back routes require the operator token", async () => {
  for (const p of ["/api/coi/writeback/setup", "/api/coi/writeback/status", "/api/coi/writeback/sweep", "/api/coi/synthetic/seed"]) {
    const res = await worker.fetch(new Request("https://w.example" + p, { method: "POST", headers: { authorization: "Bearer " + "r".repeat(40) } }),
      { OPERATOR_TOKEN: "o".repeat(40), RUNNER_TOKEN: "r".repeat(40) });
    assert.equal(res.status, 401, p);
  }
});
