import assert from "node:assert/strict";
import { File } from "node:buffer";
import test from "node:test";
import { submitAshbyApplication } from "./ashby-application.mjs";

const application = {
  apiKey: "fictional-employer-key",
  jobPostingId: "726804e8-240c-4217-bebb-c43bdf06e28f",
  answers: { _systemfield_name: "Jane Doe", _systemfield_email: "jane@example.test" },
  attachments: {
    _systemfield_resume: new File(["synthetic resume"], "resume.txt"),
    cover_letter: new File(["synthetic pitch"], "pitch.txt"),
  },
};

test("serializes both documents and returns a verified test receipt", async () => {
  const receipt = await submitAshbyApplication(application, async (url, options) => {
    assert.equal(url, "https://api.ashbyhq.com/applicationForm.submit");
    assert.equal(options.redirect, "error");
    assert.equal(options.headers.Authorization, "Basic " + btoa(application.apiKey + ":"));
    const request = new Request(url, options);
    const form = await request.formData();
    assert.equal(form.get("jobPostingId"), application.jobPostingId);
    assert.equal(form.get("allowSubmissionForUnpublishedJobPosting"), "false");
    const fields = Object.fromEntries(
      JSON.parse(form.get("applicationForm")).fieldSubmissions.map(({ path, value }) => [path, value]),
    );
    assert.equal(fields._systemfield_name, "Jane Doe");
    assert.equal(fields._systemfield_email, "jane@example.test");
    assert.equal(await form.get(fields._systemfield_resume).text(), "synthetic resume");
    assert.equal(await form.get(fields.cover_letter).text(), "synthetic pitch");
    return Response.json({ success: true, results: { submittedFormInstance: { id: "test-receipt" } } });
  });
  assert.deepEqual(receipt, { provider: "ashby", receiptId: "test-receipt" });
});

test("missing credential stops before any request", async () => {
  await assert.rejects(
    submitAshbyApplication({ ...application, apiKey: "" }, () => assert.fail("unexpected request")),
    /ASHBY_EMPLOYER_CREDENTIAL_REQUIRED/,
  );
});

test("blocked or missing receipts cannot be reported as submitted", async () => {
  for (const results of [{ blocked: true }, {}]) {
    await assert.rejects(
      submitAshbyApplication(application, () => Response.json({ success: true, results })),
      /ASHBY_SUBMISSION_UNCONFIRMED/,
    );
  }
});
