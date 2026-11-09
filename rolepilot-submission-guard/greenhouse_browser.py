"""Prepare a Greenhouse form in an isolated Playwright context."""


def prepare_greenhouse(page, preparation, profile):
    if (
        preparation.provider != "greenhouse"
        or preparation.status != "READY_FOR_BROWSER_PREPARATION"
        or preparation.submitted
    ):
        raise ValueError("A ready Greenhouse preparation is required")

    page.goto(preparation.url, wait_until="domcontentloaded")
    form = page.locator("form").filter(has=page.get_by_label("Email", exact=True))
    for label in ("First Name", "Last Name", "Email"):
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
