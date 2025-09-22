#!/usr/bin/env python
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click",
#     "grafana-client",
#     "python-dotenv",
# ]
# ///

# Generates rough stats so we have something to compare against.
#
# Usage: uv run grafana_stats.py > data_grafana/SOMEFILE

import os

import click
from dotenv import load_dotenv
from grafana_client import GrafanaApi, TokenAuth


load_dotenv()


GRAFANA_URL = os.getenv("GRAFANA_URL")
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN")


@click.command
@click.pass_context
def main(ctx):
    click.echo(f"Using: {GRAFANA_URL}")
    click.echo(f"Using: {'*' * (len(GRAFANA_TOKEN) - 4)}{GRAFANA_TOKEN[-4:]}")
    grafana = GrafanaApi.from_url(
        url=GRAFANA_URL, 
        credential=TokenAuth(token=GRAFANA_TOKEN)
    )

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
        click.echo(f"{item['id']}\t{item['title']}\t{item['isPaused']}\t{item['updated']}")
    click.echo()
    click.echo(f"total: {count}")


if __name__ == "__main__":
    main()
