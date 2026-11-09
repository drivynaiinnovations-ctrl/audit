"""Prepare ATS forms in an isolated Playwright context."""

import re

from ats_providers import ASSISTED_DOMAINS


def prepare_greenhouse(page, preparation, profile, resume=None, *, letter=None):
    open_preparation(page, preparation, "greenhouse")
    return fill_required_fields(page, profile, ("First Name", "Last Name", "Email"), resume, letter=letter)


def prepare_lever(page, preparation, profile, resume=None, *, letter=None):
    open_preparation(page, preparation, "lever")
    return fill_required_fields(page, profile, ("Full name", "Email", "Phone"), resume, letter=letter)


def prepare_workday(page, preparation, profile=None, resume=None, *, letter=None):
    open_preparation(page, preparation, "workday")
    if page.get_by_role("button", name="Sign In", exact=True).is_visible():
        return "HOLD_SIGN_IN"
    if profile is not None:
        return fill_required_fields(page, profile, ("First Name", "Last Name", "Email"), resume, letter=letter)
    return "HOLD_REVIEW"


def prepare_assisted(page, preparation, profile, resume=None, *, letter=None):
    """Prepare a labeled application form and report missing required answers."""
    if preparation.provider not in ASSISTED_DOMAINS:
        raise ValueError("Unsupported assisted provider")
    open_preparation(page, preparation, preparation.provider)
    return fill_required_fields(page, profile, ("First Name", "Last Name", "Email"), resume, letter=letter)


def open_preparation(page, preparation, provider):
    if (
        preparation.provider != provider
        or preparation.status != "READY_FOR_BROWSER_PREPARATION"
        or preparation.submitted
    ):
        raise ValueError(f"A ready {provider} preparation is required")
    page.goto(preparation.url, wait_until="domcontentloaded")


def fill_required_fields(page, profile, labels, resume=None, *, letter=None):
    form = page.locator("form").filter(has=page.get_by_label("Email", exact=True))
    for label in labels:
        if profile.get(label):
            form.get_by_label(label, exact=True).fill(profile[label])

    if resume is not None:
        attach_resume(form, resume)

    if letter is not None:
        prepare_letter(form, letter)

    return form.locator("input[required]:not([type=hidden]), textarea[required], select[required]").evaluate_all(
        "(fields) => fields.filter(field => field.validity.valueMissing)"
        """.map(field => {
            const label = field.labels?.[0]?.cloneNode(true);
            label?.querySelectorAll('input, select, textarea, button').forEach(control => control.remove());
            return label?.textContent.trim() || field.name;
        })"""
    )


def attach_resume(form, resume):
    """Attach the selected file and verify the browser retained it."""
    label = re.compile(r"^(?:(?:upload|attach)\s+)?(?:r[eé]sum[eé](?:\s*/\s*cv)?|cv)\s*\*?$", re.IGNORECASE)
    field = form.get_by_label(label).and_(form.locator('input[type="file"]'))
    if field.count() != 1:
        raise ValueError("Résumé attachment needs review: expected one labeled file input")
    field.set_input_files(resume)
    if field.evaluate("(input) => input.files.length") != 1:
        raise ValueError("Résumé attachment needs review: no file retained by the form")


def prepare_letter(form, letter):
    """Use the letter field matching the supplied text or attachment."""
    label = re.compile(r"^(?:(?:upload|attach)\s+)?(?:cover|pitch)\s+letter\s*\*?$", re.IGNORECASE)
    if isinstance(letter, str):
        if not letter.strip():
            raise ValueError("Letter needs review: text is empty")
        field = form.get_by_label(label).and_(form.locator('textarea, input[type="text"], input:not([type])'))
        if field.count() != 1:
            raise ValueError("Letter needs review: expected one labeled text field")
        field.fill(letter)
        if field.input_value() != letter:
            raise ValueError("Letter needs review: form did not retain the text")
        return

    field = form.get_by_label(label).and_(form.locator('input[type="file"]'))
    if field.count() != 1:
        raise ValueError("Letter needs review: expected one labeled file input")
    field.set_input_files(letter)
    if field.evaluate("(input) => input.files.length") != 1:
        raise ValueError("Letter needs review: form did not retain the file")


def preparation_context(browser, preparation, fixture_html):
    """Serve one simulated application document and deny every other request."""
    context = browser.new_context(service_workers="block")

    def route_request(route):
        request = route.request
        if (
            request.method == "GET"
            and request.url == preparation.url
            and request.is_navigation_request()
        ):
            route.fulfill(content_type="text/html; charset=utf-8", body=fixture_html)
        else:
            route.abort("blockedbyclient")

    context.route("**/*", route_request)
    return context
