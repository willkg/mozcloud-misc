#!/usr/bin/env python
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click",
#     "grafana-client",
#     "rich",
#     "python-dotenv",
# ]
# ///

# Look up all the data related to a specific contact point.
#
# Usage: uv run contact_point_lookup.py CONTACTPOINT

import os

import click
from dotenv import load_dotenv
from grafana_client import GrafanaApi, TokenAuth
from rich.console import Console


load_dotenv()


GRAFANA_URL = os.getenv("GRAFANA_URL")
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN")


@click.command
@click.pass_context
def main(ctx):
    console = Console()

    click.echo(f"Using: {GRAFANA_URL}")
    click.echo(f"Using: {'*' * (len(GRAFANA_TOKEN) - 4)}{GRAFANA_TOKEN[-4:]}")
    grafana = GrafanaApi.from_url(
        url=GRAFANA_URL, 
        credential=TokenAuth(token=GRAFANA_TOKEN)
    )

    # dashboards = grafana.search.search_dashboards()
    # click.echo("grafana.search.search_dashboards()")
    # click.echo()
    # count = len(dashboards)
    # count_no_folder = 0
    # for item in sorted(dashboards, key=lambda item: item["title"].lower()):
    #     click.echo(f"{item['id']}\t{item['title']}\t{item.get('folderTitle', '--')}")
    #     if "folderTitle" not in item:
    #         count_no_folder += 1
    # click.echo()
    # click.echo(f"total: {count}")
    # click.echo(f"totel no folder: {count_no_folder}")
    # click.echo()

    alert_rules = grafana.alertingprovisioning.get_alertrules_all()
    click.echo("grafana.alertingprovisioning.get_alertrules_all()")
    click.echo()
    count = len(alert_rules)
    click.echo("id\tuid\ttitle\tisPaused\tupdated")
    console.print(alert_rules[0])
    # for item in sorted(alert_rules, key=lambda item: item["title"].lower()):
    #     click.echo(f"{item['id']}\t{item['uid']}\t{item['title']}\t{item['isPaused']}\t{item['updated']}")
    # click.echo()
    # click.echo(f"total: {count}")

    contact_points = grafana.alertingprovisioning.get_contactpoints()
    click.echo("grafana.alertingprovisioning.get_contactpoints()")
    click.echo()
    count = len(contact_points)
    console.print(contact_points[0])
    click.echo("uid\tname\ttype")
    for item in sorted(contact_points, key=lambda item: item["name"].lower()):
        click.echo(f"{item['uid']}\t{item['name']}\t{item['type']}")
    click.echo()
    click.echo(f"total: {count}")

    policy_tree = grafana.alertingprovisioning.get_notification_policy_tree()
    console.print(policy_tree)


if __name__ == "__main__":
    main()
