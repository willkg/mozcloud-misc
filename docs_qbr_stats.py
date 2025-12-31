#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "arrow",
#     "click",
#     "python-dotenv",
#     "requests",
#     "rich",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Computes stats for MozCloud Customer documentation as of right now.
"""

import os
import time
from typing import Any, Dict, List, Optional

import arrow
import click
from dotenv import load_dotenv
import requests
from rich import print


load_dotenv()


def get_child_pages(
    base_url: str,
    username: str,
    token: str,
    page_id: str,
    limit: int = 200,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
    request_timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Return Python list of all child pages for a Confluence page.

    It uses the REST API:

    GET /wiki/rest/api/content/{id}/child/page

    """
    base_url = base_url.rstrip("/")

    # Cloud commonly uses /wiki; the API path includes it. If the user already
    # provided a URL ending with /wiki, this still works.
    api_root = f"{base_url}/rest/api"

    session = requests.Session()
    session.auth = (username, token)
    session.headers.update({"Accept": "application/json"})

    def _get(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                resp = session.get(url, params=params, timeout=request_timeout)

                # Rate limiting / transient errors
                if resp.status_code in (429, 500, 502, 503, 504):
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after is not None:
                        sleep_for = float(retry_after)
                    else:
                        sleep_for = backoff_seconds * (2 ** attempt)
                    time.sleep(sleep_for)
                    continue

                resp.raise_for_status()
                return resp.json()

            except Exception as exc:
                last_exc = exc
                time.sleep(backoff_seconds * (2 ** attempt))

        raise RuntimeError(f"Confluence request failed after {max_retries} retries") from last_exc

    def _get_history(page_id: str, limit: int = 200):
        versions = []
        start = 0

        while True:
            url = f"{api_root}/content/{page_id}/version"
            data = _get(url=url, params={"start": start, "limit": limit})

            results = data.get("results", [])
            versions.extend(results)

            if len(results) < limit:
                break

            start += len(results)

        return versions

    results: List[Dict[str, Any]] = []
    stack: List[str] = [str(page_id)]  # DFS over page IDs

    # Get the top-level page
    data = _get(f"{api_root}/content/{page_id}", params={"expand": "version,space"})
    data["history"] = _get_history(page_id)
    results.append(data)

    # Get all the child pages
    while stack:
        current_id = stack.pop()

        start = 0
        while True:
            # Get the page data
            data = _get(
                f"{api_root}/content/{current_id}/child/page",
                params={"limit": limit, "start": start, "expand": "version,space"}
            )

            page_items = data.get("results", []) or []
            for p in page_items:
                child_id = str(p.get("id"))
                if not child_id:
                    continue

                p["history"] = _get_history(p["id"])
                results.append(p)

                # Recurse into this child
                stack.append(child_id)

            # Pagination
            size = len(page_items)
            if size == 0:
                break

            # Confluence v1 typically returns: start, limit, size, _links.next
            next_link = (data.get("_links") or {}).get("next")
            if next_link:
                # If server provides next, prefer it
                # next_link is usually a relative path like "/rest/api/...&start=200"
                start = start + size
                continue

            # Otherwise rely on start/limit
            if size < limit:
                break
            start += size

    return results


@click.command()
@click.argument("year")
@click.argument("quarter")
@click.pass_context
def main(ctx, year, quarter):
    """
    Computes stats for MozCloud customer documentation for right now.

    Create an API token in Confluence and set these in the `.env` file:

    \b
    * CONFLUENCE_USERNAME
    * CONFLUENCE_TOKEN
    * CONFLUENCE_URL
    """
    year = int(year.strip())
    quarter = int(quarter.strip())

    if quarter == 1:
        date_start = arrow.get(f"{year}-01-01 00:00:00")
        date_end = arrow.get(f"{year}-03-31 23:59:59")
    elif quarter == 2:
        date_start = arrow.get(f"{year}-04-01 00:00:00")
        date_end = arrow.get(f"{year}-06-30 23:59:59")
    elif quarter == 3:
        date_start = arrow.get(f"{year}-07-01 00:00:00")
        date_end = arrow.get(f"{year}-09-30 23:59:59")
    elif quarter == 4:
        date_start = arrow.get(f"{year}-10-01 00:00:00")
        date_end = arrow.get(f"{year}-12-31 23:59:59")
    else:
        raise ValueError("quarter must be 1, 2, 3, or 4")

    # Page id for MozCloud customer documentation
    page_id = 1517453510

    click.echo("Fetching Confluence data...")
    child_pages = get_child_pages(
        base_url=os.environ["CONFLUENCE_URL"].strip(),
        username=os.environ["CONFLUENCE_USERNAME"].strip(),
        token=os.environ["CONFLUENCE_PASSWORD"].strip(),
        page_id=page_id,
    )
    click.echo("Determining statistics data...")
    number_edited_this_quarter = 0
    for page in child_pages:
        for item in page["history"]:
            last_updated = arrow.get(item["when"])
            if date_start <= last_updated <= date_end:
                number_edited_this_quarter += 1
                break

    click.echo(f"{date_start} to {date_end}")
    click.echo(f"Number of pages now: {len(child_pages)}")
    click.echo(f"Number edited this quarter: {number_edited_this_quarter}")

    # FIXME(willkg): breakdown by label? need to get labels Figure out how many
    # edits in time frame for each page show top 10 active pages in time frame


if __name__ == "__main__":
    main()
