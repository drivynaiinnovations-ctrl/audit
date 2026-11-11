import test from "node:test";
import assert from "node:assert/strict";
import { evaluateCOI, parseScreeningAnswers } from "./coi.mjs";
import { validateResult } from "./prep.mjs";
import { driveFileId } from "./google.mjs";
import worker from "./index.mjs";

const H = ["Opportunity ID", "Company", "Role", "Direct Source URL", "Status", "Applied", "Application Authorization", "Resume URL"];
const MH = ["Manifest ID", "Opportunity ID", "Approved Resume", "Approved Cover Letter", "Cover Letter Required",
  "Cross-Table Duplicate Gate", "Submission Gate Decision", "Approved Screening Answers", "Supporting Documents"];
const R = "https://drive.google.com/file/d/RESUMEFILEID01/view";
const C = "https://docs.google.com/document/d/COVERFILEID001/edit";
const opp = (id, company, status = "Ready", applied = "FALSE", auth = "Authorized", url = `https://jobs.example.com/${id}`) =>
  [id, company, "Analyst", url, status, applied, auth, "https://drive.google.com/file/d/OLDRESUMEID0/view"];
const man = (id, extra = {}) => [`m-${id}`, id, extra.resume ?? R, extra.cover ?? C, extra.coverRequired ?? "",
  extra.dup ?? "CLEAR", extra.gate ?? "HOLD_MANUAL_PREFLIGHT", extra.answers ?? "", extra.supporting ?? ""];

function run(rows, manifests) {
  return evaluateCOI([H, ...rows], [MH, ...manifests]);
}
const reasonOf = (r, id) => r.blocked.find((b) => b.opportunity_id === id)?.reason;

test("imports only unapplied, active, authorized rows with manifest documents", () => {
  const r = run([opp("ok", "A"), opp("ap", "B", "Ready", "TRUE"), opp("rj", "C", "Rejected"), opp("cl", "D", "Role closed"),
    opp("wd", "E", "Withdrawn"), opp("du", "F", "Duplicate"), opp("ua", "G", "Ready", "FALSE", ""), opp("na", "H", "Ready", "FALSE", "Not authorized"),
    opp("nd", "I"), opp("nm", "J"), opp("st", "K", "Applied - follow up")],
  [man("ok"), man("ap"), man("rj"), man("cl"), man("wd"), man("du"), man("ua"), man("na"), man("nd", { resume: "" }), man("st")]);
  assert.deepEqual(r.eligible.map((e) => e.opportunity_id), ["ok"]);
  assert.equal(r.eligible[0].documents.resume, R, "manifest résumé is authoritative");
  const expect = { ap: "BLOCK_APPLIED", rj: "BLOCK_REJECTED", cl: "BLOCK_CLOSED", wd: "BLOCK_WITHDRAWN", du: "BLOCK_DUPLICATE",
    ua: "BLOCK_UNAUTHORIZED", na: "BLOCK_UNAUTHORIZED", nd: "BLOCK_DOCUMENTS_INCOMPLETE", nm: "BLOCK_DOCUMENTS_INCOMPLETE", st: "BLOCK_APPLIED" };
  for (const [id, reason] of Object.entries(expect)) assert.equal(reasonOf(r, id), reason, id);
});

test("'Not applied' status is not mistaken for applied", () => {
  const r = run([opp("x", "A", "Not applied")], [man("x")]);
  assert.equal(r.eligible.length, 1);
});

test("duplicates of applied roles and in-sheet duplicates are blocked", () => {
  const r = run([opp("a1", "Acme", "Applied", "TRUE"), opp("a2", "ACME", "Ready"), opp("b1", "Beta"), opp("b2", "Beta")],
    [man("a2"), man("b1"), man("b2")]);
  assert.equal(reasonOf(r, "a2"), "BLOCK_DUPLICATE_OF_APPLIED");
  assert.equal(reasonOf(r, "b2"), "BLOCK_DUPLICATE");
  assert.deepEqual(r.eligible.map((e) => e.opportunity_id), ["b1"]);
});

test("manifest gates, optional cover letter, supporting docs and screening answers", () => {
  const r = run([opp("g", "G"), opp("o", "O"), opp("s", "S"), opp("bad", "Bad")], [
    man("g", { dup: "BLOCK_EXISTING_APPLICATION" }),
    man("o", { cover: "", coverRequired: "Optional", answers: '{"Are you authorized to work in the US?":"Yes"}' }),
    man("s", { supporting: "https://drive.google.com/file/d/PORTFOLIOID01/view" }),
    man("bad", { supporting: "not-a-url" }),
  ]);
  assert.equal(reasonOf(r, "g"), "BLOCK_APPLIED");
  assert.equal(reasonOf(r, "bad"), "BLOCK_DOCUMENTS_INCOMPLETE");
  const o = r.eligible.find((e) => e.opportunity_id === "o");
  assert.equal(o.documents.cover_letter, "");
  assert.equal(o.approved_answers["Are you authorized to work in the US?"], "Yes");
  assert.equal(r.eligible.find((e) => e.opportunity_id === "s").documents.supporting.length, 1);
});

test("schema drift fails closed", () => {
  assert.throws(() => evaluateCOI([["Opportunity ID", "Company"]], [MH]), /COI_SCHEMA_MISSING/);
});

test("screening answer parsing", () => {
  assert.deepEqual(parseScreeningAnswers("Q1 => A1\nQ2 :: A2").answers, { Q1: "A1", Q2: "A2" });
  assert.equal(parseScreeningAnswers("free text").unreadable, true);
});

test("runner results that claim a submission are rejected", () => {
  const ok = { status: "READY_FOR_REVIEW_NOT_SUBMITTED", pages: 3, submitted: false, final_submit_clicked: false };
  assert.equal(validateResult(ok), "");
  assert.equal(validateResult({ ...ok, submitted: true }), "SUBMISSION_VIOLATION");
  assert.equal(validateResult({ ...ok, final_submit_clicked: true }), "SUBMISSION_VIOLATION");
  assert.equal(validateResult({ ...ok, submitted: undefined }), "SUBMISSION_VIOLATION");
  assert.equal(validateResult({ ...ok, status: "SUBMITTED" }), "INVALID_STATUS");
});

test("drive IDs only from Google hosts", () => {
  assert.equal(driveFileId(R), "RESUMEFILEID01");
  assert.equal(driveFileId("https://evil.example/file/d/RESUMEFILEID01"), "");
});

test("pipeline routes require their own tokens and fixtures need audit mode", async () => {
  const env = { OPERATOR_TOKEN: "o".repeat(40), RUNNER_TOKEN: "r".repeat(40), COI_SHEET_ID: "sheet" };
  const call = (path, token, body = {}) => worker.fetch(new Request("https://x.test" + path, {
    method: "POST", headers: { authorization: "Bearer " + token, "content-type": "application/json" }, body: JSON.stringify(body) }), env);
  assert.equal((await call("/api/coi/import", "r".repeat(40))).status, 401);
  assert.equal((await call("/api/runner/claim", "o".repeat(40))).status, 401);
  assert.equal((await call("/api/coi/import", "o".repeat(40), { fixture: {} })).status, 403);
  const live = await call("/api/coi/import", "o".repeat(40));
  assert.equal(live.status, 503);
  assert.equal((await live.json()).reason, "GOOGLE_CREDENTIAL_MISSING");
  assert.equal((await worker.fetch(new Request("https://x.test/api/execute", { method: "POST" }), env)).status, 403);
});
