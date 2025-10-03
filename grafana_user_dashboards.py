#!/usr/bin/env python
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click",
#     "grafana-client",
#     "python-dotenv",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Usage: uv run user_dashboards.py [USER]

Lists all the dashboards specified user created or edited.
"""

import json
import os

import click
from dotenv import load_dotenv
from grafana_client import GrafanaApi, TokenAuth


load_dotenv()


GRAFANA_URL = os.getenv("GRAFANA_URL")
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN")


@click.command
@click.option("--verbose/--no-verbose", default=False)
@click.argument("user")
@click.pass_context
def main(ctx, verbose, user):
    """
    Lists all the dashboards specified user created or edited.

    Create a Grafana API token and set these in the `.env` file:

    \b
    * GRAFANA_URL
    * GRAFANA_TOKEN
    """

    data_path = "data_grafana/dashboard_data.json"
    if not os.path.exists(data_path):
        data = []
        click.echo("Generating dashboard_data.json ...")
        click.echo(f"Using: {GRAFANA_URL}")
        click.echo(f"Using: {'*' * (len(GRAFANA_TOKEN) - 4)}{GRAFANA_TOKEN[-4:]}")
        grafana = GrafanaApi.from_url(
            url=GRAFANA_URL, credential=TokenAuth(token=GRAFANA_TOKEN)
        )

        dashboards = grafana.search.search_dashboards()
        for item in dashboards:
            dashboard_id = item["id"]
            item["versionData"] = []

            versions = grafana.dashboard_versions.get_dashboard_versions(
                dashboard_id=dashboard_id
            )
            for version in versions:
                item["versionData"].append(version)
            data.append(item)

        with open(data_path, "w") as fp:
            json.dump(data, fp)

    else:
        with open(data_path, "r") as fp:
            data = json.load(fp)

    for item in data:
        dashboard_id = item["id"]
        title = item["title"]
        url = GRAFANA_URL.rstrip("/") + item["url"]

        for version in item["versionData"]:
            if version["createdBy"].startswith(user):
                click.echo(f"{dashboard_id}\t{title}\t{url}")
                break


if __name__ == "__main__":
    main()
