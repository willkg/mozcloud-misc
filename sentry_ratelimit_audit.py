#!/usr/bin/env python
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click",
#     "python-dotenv",
#     "requests",
# ]
# ///


# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


"""
Audits Sentry project rate limits.


API tokens
==========

Store tokens in a ``.env`` file in the local directory::

    SENTRY_API_TOKEN=xxx

Usage
=====

To use this:

1. Set tokens in ``.env`` file.

2. Run::

      $ uv run sentry_ratelimit_audit.py [OPTIONS]

"""

import os

import click
from dotenv import load_dotenv
import requests


load_dotenv()


SENTRY_TOKEN = os.getenv("SENTRY_API_TOKEN")

SENTRY_API_URL = "https://sentry.io/api/0/"

SENTRY_ORGANIZATION = "mozilla"


def get_api_data(session, url):
    """Helper function to make a GET request and handle errors."""
    try:
        response = session.get(url)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        return response
    except requests.exceptions.HTTPError as err:
        click.secho(f"HTTP Error: {err}", fg="red")
        if err.response.status_code == 401:
            click.secho(
                "Authentication failed. Is your SENTRY_AUTH_TOKEN correct?", fg="red"
            )
        elif err.response.status_code == 403:
            click.secho(
                "Permission denied. Does your token have the 'project:read' scope?",
                fg="red",
            )
        elif err.response.status_code == 404:
            click.secho(
                "Resource not found. Is the organization slug correct?", fg="red"
            )
        return None
    except requests.exceptions.RequestException as err:
        click.secho(f"Request Error: {err}", fg="red")
        return None


def get_paged_data(session, url):
    has_more = True
    while has_more:
        response = get_api_data(session, url)

        yield response.json()

        link_header_next = response.links["next"]
        has_more = (
            link_header_next["rel"] == "next"
            and link_header_next["results"] == "true"
        )
        url = link_header_next["url"]


@click.command()
@click.pass_context
def cmd_sentry_audit(ctx):
    click.secho(
        f"Fetching projects for organization: {SENTRY_ORGANIZATION}...", fg="yellow"
    )

    headers = {"Authorization": f"Bearer {SENTRY_TOKEN}"}
    with requests.Session() as session:
        session.headers.update(headers)

        click.echo("-" * 40)

        count_projects = []
        count_no_ratelimit = []
        count_standard_ratelimit = []
        count_nonstandard_ratelimit = []

        # 1. Get all projects for the organization
        url = f"{SENTRY_API_URL}organizations/{SENTRY_ORGANIZATION}/projects/"

        # 2. Loop through pages
        for projects in get_paged_data(session, url):
            # 3. Loop through each project to get its keys (DSNs)
            for project in projects:
                project_slug = project["slug"]
                project_name = project["name"]
                count_projects.append(project_name)
                keys_url = (
                    f"{SENTRY_API_URL}projects/{SENTRY_ORGANIZATION}/{project_slug}/keys/"
                )
                keys = get_api_data(session, keys_url).json()

                if not keys:
                    click.echo(f"{project_name}    No DSNs found for this project.")
                    continue


                # 3. Loop through keys and check for rate limits
                for key in keys:
                    dsn = key["dsn"]["public"]

                    rate_limit = key.get("rateLimit")
                    if (
                        rate_limit
                        and rate_limit.get("count") is not None
                        and rate_limit.get("window") is not None
                    ):
                        count = rate_limit["count"]
                        window = rate_limit["window"]
                        click.secho(
                            f"{project_name}    {dsn}    enabled: ({count} / {window}s)",
                            fg="green",
                        )
                        if count == 30 and window == 60:
                            count_standard_ratelimit.append(project_name)
                        else:
                            count_nonstandard_ratelimit.append(project_name)
                    
                    else:
                        click.secho(f"{project_name}    {dsn}    disabled", fg="red")
                        count_no_ratelimit.append(project_name)

        click.echo()
        click.echo(f"Projects: {len(count_projects)}")
        click.echo(f"* standard ratelimit: {len(count_standard_ratelimit)}")
        click.echo(f"* nonstandard ratelimit: {len(count_nonstandard_ratelimit)}")
        click.echo(f"* no ratelimit: {len(count_no_ratelimit)}")


if __name__ == "__main__":
    cmd_sentry_audit()
