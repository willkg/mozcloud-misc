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
"""

import os

import click
from dotenv import load_dotenv
import requests


load_dotenv()


SENTRY_TOKEN = os.getenv("SENTRY_API_TOKEN")

SENTRY_API_URL = "https://sentry.io/api/0/"

SENTRY_ORGANIZATION = "mozilla"

COUNT = 30
WINDOW = 60  # in seconds


def change_ratelimit(session, url, project_slug, key_id, count, window):
    """Sets the rate limit for DSN key_id for project project_slug.

    :returns: current rate limit settings or None

    """
    try:
        payload = {
            "rateLimit": {
                "count": count,
                "window": window,
            }
        }
        response = session.put(url, json=payload)
        response.raise_for_status()
        return response.json().get("rateLimit")
    except requests.exceptions.HTTPError as err:
        click.secho(f"HTTP Error: {err}", fg="red")
        click.secho(f"content: {err.response.content}")
        return None
    except requests.exceptions.RequestException as err:
        click.secho(f"Request Error: {err}", fg="red")
        return None



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
            link_header_next["rel"] == "next" and link_header_next["results"] == "true"
        )
        url = link_header_next["url"]


def generate_display_dsn(hide_dsn, dsn):
    if hide_dsn:
        # dsn is like:
        # https://fb353b456839203894852929ed4b2687@o1069899.ingest.us.sentry.io/6250021
        # and we want to convert that to:
        # https://fb353XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX.ingest.us.sentry.io/6250021
        protocol, rest = dsn.split("//")
        rest_parts = rest.split(".")
        display_dsn = (
            protocol
            + "://"
            + rest_parts[0][0:5]
            + "X" * (len(rest_parts[0]) - 5)
            + ".".join(rest_parts[1:])
        )
        return display_dsn
    return dsn


@click.command()
@click.option(
    "--hide-dsn/--no-hide-dsn",
    "hide_dsn",
    default=False,
    help="Hide the DSN in output.",
)
@click.option(
    "--fix/--no-fix",
    "should_fix",
    default=False,
    help="Whether to fix a project dsn rate limit when it's not set to our guidance.",
)
@click.pass_context
def cmd_sentry_audit(ctx, hide_dsn, should_fix):
    """
    Audits Sentry project rate limits.

    Create a Sentry API token and add set this in the `.env` file:

    \b
    * SENTRY_API_TOKEN
    """

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
        fixed_ratelimit = []

        # 1. Get all projects for the organization
        url = f"{SENTRY_API_URL}organizations/{SENTRY_ORGANIZATION}/projects/"

        # 2. Loop through pages
        for projects in get_paged_data(session, url):
            # 3. Loop through each project to get its keys (DSNs)
            for project in projects:
                project_slug = project["slug"]
                project_name = project["name"]
                count_projects.append(project_name)
                keys_url = f"{SENTRY_API_URL}projects/{SENTRY_ORGANIZATION}/{project_slug}/keys/"
                keys = get_api_data(session, keys_url).json()

                if not keys:
                    click.echo(f"{project_name}    No DSNs found for this project.")
                    continue

                # 3. Loop through keys and check for rate limits
                for key in keys:
                    dsn = key["dsn"]["public"]
                    display_dsn = generate_display_dsn(hide_dsn, dsn)

                    rate_limit = key.get("rateLimit") or {}
                    if (
                        rate_limit.get("count") is not None
                        and rate_limit.get("window") is not None
                    ):
                        count = rate_limit["count"]
                        window = rate_limit["window"]
                        click.secho(
                            f"{project_name}    {display_dsn}    enabled: ({count} / {window}s)",
                            fg="green",
                        )
                        if count == COUNT and window == WINDOW:
                            count_standard_ratelimit.append(project_name)
                        else:
                            count_nonstandard_ratelimit.append(project_name)

                    else:
                        click.secho(f"{project_name}    {display_dsn}    disabled", fg="red")
                        count_no_ratelimit.append(project_name)

                    if (
                        should_fix
                        and rate_limit.get("count") is None
                        and rate_limit.get("window") is None
                    ):
                        click.echo(f"   fixing ratelimit: {project_name}    {display_dsn}")
                        input("Ok?")
                        key_id = key["id"]
                        ratelimit_url = f"{SENTRY_API_URL}projects/{SENTRY_ORGANIZATION}/{project_slug}/keys/{key_id}/"
                        new_ratelimit = change_ratelimit(
                            session=session,
                            url=ratelimit_url,
                            project_slug=project_slug,
                            key_id=key_id,
                            count=COUNT,
                            window=WINDOW,
                        )
                        click.secho(f"   new rate limit: enabled: ({new_ratelimit['count']} / {new_ratelimit['window']}s)")
                        fixed_ratelimit.append(project_slug)
                        input("Good?")

        click.echo()
        click.echo(f"Projects: {len(count_projects)}")
        click.echo("Ratelimit by DSN:")
        click.echo(f"* standard ratelimit: {len(count_standard_ratelimit)}")
        click.echo(f"* nonstandard ratelimit: {len(count_nonstandard_ratelimit)}")
        click.echo(f"* no ratelimit: {len(count_no_ratelimit)}")

        if fixed_ratelimit:
            click.echo("")
            click.echo("Fixed ratelimit for these projects that had no ratelimit set:")
            for project in fixed_ratelimit:
                click.echo(project)


if __name__ == "__main__":
    cmd_sentry_audit()
