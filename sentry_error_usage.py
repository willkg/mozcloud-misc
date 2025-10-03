#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
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
Shows last N days of Sentry error quota usage for the organization.
"""

import os

import click
from dotenv import load_dotenv
import requests


load_dotenv()


SENTRY_API_URL = "https://sentry.io/api/0/"
SENTRY_ORGANIZATION = "mozilla"
# How many days back to look at stats for
STATS_PERIOD = "30d"

SENTRY_TOKEN = os.getenv("SENTRY_API_TOKEN")


@click.command()
@click.pass_context
def cmd_sentry_usage(ctx):
    """
    Shows last N days of Sentry error quota usage for the organization.

    Create a Sentry API token and set this in the `.env` file:

    \b
    * SENTRY_API_TOKEN
    """

    headers = {"Authorization": f"Bearer {SENTRY_TOKEN}"}
    params = {
        "statsPeriod": STATS_PERIOD,
        "interval": "1d",
        "field": "sum(quantity)",
        "groupBy": "category",
        "category": "error",
        "outcome": "accepted",
    }

    stats_url = f"{SENTRY_API_URL}organizations/{SENTRY_ORGANIZATION}/stats_v2/"

    click.echo(f"Fetching daily accepted error stats for the last {STATS_PERIOD}...")

    try:
        response = requests.get(stats_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        # The data is returned in a structure with totals for each group. We
        # need to find the group for the 'error' category.
        error_group_data = None
        for group in data.get("groups", []):
            if group.get("by", {}).get("category") == "error":
                error_group_data = group
                break

        timestamps = data["intervals"]

        if not error_group_data or "series" not in error_group_data:
            click.echo("Could not find time series data for accepted errors.")
        else:
            click.echo("Daily Breakdown of error:")
            # The 'series' object contains a list of totals in order of
            # timestamps
            totals = error_group_data["totals"]
            for group in totals:
                for i in range(len(timestamps)):
                    # Truncate time from datestamp
                    date_str = timestamps[i][0:10]
                    count = error_group_data["series"][group][i]
                    click.echo(f"{date_str}: {count:,} errors")

    except requests.exceptions.HTTPError as err:
        click.echo(f"Error fetching stats: {err}")
        click.echo(f"Response body: {err.response.text}")


if __name__ == "__main__":
    cmd_sentry_usage()
