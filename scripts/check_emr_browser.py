# /// script
# dependencies = ["playwright"]
# ///
"""Run only against an isolated demo stack: this creates and archives clinical test records.

uv run scripts/check_emr_browser.py --base-url http://127.0.0.1:5173 --tokens /tmp/test-tokens.json
Install Chromium with `uv run --with playwright playwright install chromium` first.
Tokens belong to dr_wang and dr_li in the disposable test database, never production.
"""

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description="M4 browser acceptance against an isolated demo stack")
parser.add_argument("--base-url", default="http://127.0.0.1:5173")
parser.add_argument(
    "--tokens",
    required=True,
    help="Local JSON mapping dr_wang and dr_li to test access tokens; never commit this file",
)
args = parser.parse_args()
tokens = json.loads(Path(args.tokens).read_text())
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"),
        args=["--no-sandbox"],
    )
    context = browser.new_context()
    context.add_init_script(
        'localStorage.setItem("dwp.access-token", ' + json.dumps(tokens["dr_wang"]) + ")"
    )
    page = context.new_page()
    page.goto(args.base_url + "/records")
    page.get_by_label("Patient", exact=True).select_option("P20260001")
    page.get_by_role("button", name="New draft", exact=True).click()
    page.get_by_label("Chief complaint").fill("Browser acceptance symptom")
    page.get_by_label("Diagnosis").fill("Browser acceptance diagnosis")
    page.get_by_label("Note date").fill("2026-09-19")
    page.get_by_label("History", exact=True).fill("Draft must survive reload after network failure")
    page.route(
        "**/api/emr/records/*",
        lambda route: route.abort() if route.request.method == "PATCH" else route.continue_(),
    )
    page.get_by_role("button", name="Save and submit", exact=True).click()
    page.get_by_role("alert").filter(has_text="Your draft is retained").wait_for()
    page.unroute("**/api/emr/records/*")
    page.reload()
    page.get_by_text("Restored your local draft.", exact=True).wait_for()
    assert (
        page.get_by_label("History", exact=True).input_value()
        == "Draft must survive reload after network failure"
    )
    page.get_by_role("button", name="Save draft", exact=True).click()
    page.get_by_text("Draft saved.", exact=True).wait_for()
    second = context.new_page()
    second.goto(page.url)
    second.get_by_label("Chief complaint").wait_for()
    page.get_by_label("Chief complaint").fill("Updated in first tab")
    with page.expect_response(
        lambda r: "/emr/records/" in r.url and r.request.method == "PATCH"
    ) as response:
        page.get_by_role("button", name="Save draft", exact=True).click()
    assert response.value.status == 200
    second.get_by_label("History", exact=True).fill("Stale tab changes retained")
    second.get_by_role("button", name="Save draft", exact=True).click()
    second.get_by_role("alert").filter(has_text="record changed").wait_for()
    assert second.get_by_label("History", exact=True).input_value() == "Stale tab changes retained"
    second.close()
    page.get_by_label("Drug", exact=True).select_option("AMOX500")
    page.get_by_role("button", name="Validate and save", exact=True).click()
    page.get_by_role("heading", name="Order blocked", exact=True).wait_for()
    assert page.get_by_role("button", name="Confirm and continue").count() == 0
    page.get_by_role("button", name="Cancel / change drug").click()
    page.get_by_label("Drug", exact=True).select_option("FURO20")
    page.get_by_label("Dose with units").fill("80mg")
    page.get_by_role("button", name="Validate and save", exact=True).click()
    page.get_by_role("heading", name="Dose warning", exact=True).wait_for()
    page.get_by_role("button", name="Confirm and continue").click()
    page.get_by_role("button", name="Modify", exact=True).wait_for()
    page.get_by_role("button", name="Save and submit", exact=True).click()
    page.get_by_text("Submitted for review.", exact=True).wait_for()
    record_url = page.url
    assert page.get_by_role("button", name="Save draft", exact=True).count() == 0
    page.goto(args.base_url + "/my-submissions")
    page.get_by_role("main").get_by_role("heading", name="My submissions", exact=True).wait_for()
    assert page.get_by_role("button", name="Pending review", exact=True).count() == 0
    reviewer = browser.new_context()
    reviewer.add_init_script(
        'localStorage.setItem("dwp.access-token", ' + json.dumps(tokens["dr_li"]) + ")"
    )
    senior = reviewer.new_page()
    senior.goto(args.base_url + "/review")
    with senior.expect_response(
        lambda r: "/review" in r.url and r.request.method == "POST"
    ) as response:
        senior.get_by_role("button", name="Approve and archive", exact=True).last.click()
    assert response.value.status == 200
    page.goto(record_url)
    page.get_by_text(
        "Archived. The original record and its orders are read-only.", exact=True
    ).wait_for()
    assert page.get_by_label("Chief complaint").is_disabled()
    assert page.get_by_role("button", name="Save draft", exact=True).count() == 0
    page.get_by_label("Treatment plan addendum").fill("Browser amendment")
    page.get_by_role("button", name="Append new version", exact=True).click()
    page.get_by_text("Version 3 ·", exact=False).first.wait_for()
    browser.close()
print(
    "PASS: browser draft persistence, allergy block, dose confirmation, submission, role visibility, archive and amendment"
)
