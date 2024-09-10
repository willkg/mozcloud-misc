#!/usr/bin/env python
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click",
#     "grafana-client",
#     "python-dotenv",
# ]
# ///

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

    users = grafana.users.search_users()
    click.echo(users)


if __name__ == "__main__":
    main()
