"""Prepare ATS forms in an isolated Playwright context."""


def prepare_greenhouse(page, preparation, profile):
    open_preparation(page, preparation, "greenhouse")
    return fill_required_fields(page, profile, ("First Name", "Last Name", "Email"))


def prepare_lever(page, preparation, profile):
    open_preparation(page, preparation, "lever")
    return fill_required_fields(page, profile, ("Full name", "Email", "Phone"))


def prepare_workday(page, preparation):
    open_preparation(page, preparation, "workday")
    if page.get_by_role("button", name="Sign In", exact=True).is_visible():
        return "HOLD_SIGN_IN"
    return "HOLD_REVIEW"


def open_preparation(page, preparation, provider):
    if (
        preparation.provider != provider
        or preparation.status != "READY_FOR_BROWSER_PREPARATION"
        or preparation.submitted
    ):
        raise ValueError(f"A ready {provider} preparation is required")
    page.goto(preparation.url, wait_until="domcontentloaded")


def fill_required_fields(page, profile, labels):
    form = page.locator("form").filter(has=page.get_by_label("Email", exact=True))
    for label in labels:
        if profile.get(label):
            form.get_by_label(label, exact=True).fill(profile[label])

    return form.locator("input[required]:not([type=hidden]), textarea[required], select[required]").evaluate_all(
        "(fields) => fields.filter(field => field.validity.valueMissing)"
        ".map(field => field.labels?.[0]?.textContent.trim() || field.name)"
    )


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
            route.fulfill(content_type="text/html", body=fixture_html)
        else:
            route.abort("blockedbyclient")

    context.route("**/*", route_request)
    return context
