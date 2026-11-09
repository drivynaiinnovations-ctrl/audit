import { submitAshbyApplication } from "./ashby-application.mjs";

// The only input is a server-generated identifier. The transport is in-process.
export async function runAshbySandbox(id) {
  const receipt = await submitAshbyApplication({
    apiKey: "sandbox-only",
    jobPostingId: "e9ed20fd-d45f-4aad-8a00-a19bfba0083e",
    answers: { _systemfield_name: "Jane Doe", _systemfield_email: "jane@example.test" },
    attachments: {
      _systemfield_resume: new File(["Synthetic résumé"], "resume.txt"),
      cover_letter: new File(["Synthetic cover letter"], "cover-letter.txt"),
    },
  }, async (url, options) => {
    const form = await new Request(url, options).formData();
    const { fieldSubmissions } = JSON.parse(form.get("applicationForm"));
    const fields = Object.fromEntries(fieldSubmissions.map(({ path, value }) => [path, value]));
    if (
      fields._systemfield_email !== "jane@example.test" ||
      await form.get(fields._systemfield_resume)?.text() !== "Synthetic résumé" ||
      await form.get(fields.cover_letter)?.text() !== "Synthetic cover letter"
    ) return Response.json({ success: false }, { status: 422 });

    return Response.json({ success: true, results: { submittedFormInstance: { id } } });
  });
  return { ...receipt, sandbox: true };
}
