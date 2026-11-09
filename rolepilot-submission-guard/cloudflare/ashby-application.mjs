// Employer-authorized Ashby submission contract. The Worker does not enable it.
const endpoint = "https://api.ashbyhq.com/applicationForm.submit";

export async function submitAshbyApplication({ apiKey, jobPostingId, answers, attachments }, send) {
  if (!apiKey?.trim()) throw new Error("ASHBY_EMPLOYER_CREDENTIAL_REQUIRED");
  if (!/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(jobPostingId)) {
    throw new Error("INVALID_ASHBY_POSTING");
  }

  const form = new FormData();
  const fieldSubmissions = [];
  const paths = new Set();
  for (const [path, value] of Object.entries(answers)) {
    paths.add(path);
    fieldSubmissions.push({ path, value });
  }
  for (const [path, file] of Object.entries(attachments)) {
    if (paths.has(path) || !(file instanceof Blob) || !file.size || !file.name) {
      throw new Error("INVALID_ASHBY_ATTACHMENT");
    }
    const part = "attachment_" + fieldSubmissions.length;
    form.set(part, file, file.name);
    fieldSubmissions.push({ path, value: part });
  }
  form.set("jobPostingId", jobPostingId);
  form.set("allowSubmissionForUnpublishedJobPosting", "false");
  form.set("applicationForm", JSON.stringify({ fieldSubmissions }));

  const response = await send(endpoint, {
    method: "POST",
    headers: { Authorization: "Basic " + btoa(apiKey + ":") },
    body: form,
    redirect: "error",
  });
  if (!response.ok) throw new Error("ASHBY_SUBMISSION_UNCONFIRMED");
  const payload = await response.json();
  const receipt = payload.results?.submittedFormInstance;
  if (payload.success !== true || payload.blocked || payload.results?.blocked || !receipt?.id) {
    throw new Error("ASHBY_SUBMISSION_UNCONFIRMED");
  }
  return { provider: "ashby", receiptId: receipt.id };
}
