#!/usr/bin/env python
# /// script
# requires-python = ">=3.12"
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
Generates rough stats so we have a snapshot of what's in Grafana
to compare one period to another.
"""

import os

import click
from dotenv import load_dotenv
from grafana_client import GrafanaApi, TokenAuth


load_dotenv()


GRAFANA_URL = os.getenv("GRAFANA_URL")
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN")


@click.command
@click.option("--url", default=None)
@click.option("--token", default=None)
@click.pass_context
def main(ctx, url, token):
    """
    Generates rough stats so we have a snapshot of what's in Grafana
    to compare one period to another.

    Create a Grafana API token and set these in the `.env` file:

    \b
    * GRAFANA_URL
    * GRAFANA_TOKEN
    """

    url = url or GRAFANA_URL
    token = token or GRAFANA_TOKEN

    click.echo(f"Using: {url}")
    click.echo(f"Using: {'*' * (len(token) - 4)}{token[-4:]}")
    grafana = GrafanaApi.from_url(url=url, credential=TokenAuth(token=token))

    dashboards = grafana.search.search_dashboards()
    click.echo("grafana.search.search_dashboards()")
    click.echo()
    count = len(dashboards)
    count_no_folder = 0
    for item in sorted(dashboards, key=lambda item: item["title"].lower()):
        click.echo(f"{item['id']}\t{item['title']}\t{item.get('folderTitle', '--')}")
        if "folderTitle" not in item:
            count_no_folder += 1
    click.echo()
    click.echo(f"total: {count}")
    click.echo(f"totel no folder: {count_no_folder}")
    click.echo()

    notifications = grafana.notifications.get_channels()
    click.echo("grafana.notifications.get_channels()")
    click.echo()
    count = len(notifications)
    for item in sorted(notifications, key=lambda item: item["name"].lower()):
        click.echo(f"{item['id']}\t{item['name']}\t{item['updated']}")
    click.echo()
    click.echo(f"total: {count}")
    click.echo()

    alert_rules = grafana.alertingprovisioning.get_alertrules_all()
    click.echo("grafana.alertingprovisioning.get_alertrules_all()")
    click.echo()
    count = len(alert_rules)
    for item in sorted(alert_rules, key=lambda item: item["title"].lower()):
        click.echo(
            f"{item['id']}\t{item['title']}\t{item['isPaused']}\t{item['updated']}"
        )
    click.echo()
    click.echo(f"total: {count}")


if __name__ == "__main__":
    main()
