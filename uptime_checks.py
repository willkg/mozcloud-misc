#!/usr/bin/env python
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click",
#     "python-dotenv",
#     "requests",
#     "rich",
# ]
# ///

# Usage: uv run uptime_checks.py [OPTIONS]
#
# Lists all the uptime checks in Pingdom plus some stats.

import json
import os

import click
from dotenv import load_dotenv
import requests
from rich.console import Console
from rich.table import Table


load_dotenv()


PINGDOM_API_TOKEN = os.getenv("PINGDOM_API_TOKEN")

PINGDOM_API_URL = "https://api.pingdom.com/api/3.1"

CHECKS_DIR = "checks/"

HEADERS = {"Authorization": f"Bearer {PINGDOM_API_TOKEN}", "Accept-Encoding": "gzip"}


def get_checks():
    resp = requests.get(f"{PINGDOM_API_URL}/checks", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["checks"]


def get_check(check_id):
    resp = requests.get(f"{PINGDOM_API_URL}/checks/{check_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["check"]


@click.command()
@click.pass_context
def main(ctx):
    console = Console()
    checks = get_checks()

    checks.sort(key=lambda item: item["name"])

    table = Table()
    table.add_column("id")
    table.add_column("name")
    table.add_column("tags")
    table.add_column("resolution")
    table.add_column("type")

    heartbeat_count = 0
    all_tags = set()
    frequency_counter = {}
    type_counter = {}
    env_counter = {}

    for check in checks:
        path = f"{CHECKS_DIR}/check_{check["id"]}.json"
        if os.path.exists(path):
            with open(path, "r") as fp:
                check_data = json.load(fp)

        else:
            check_data = get_check(check["id"])
            with open(f"{CHECKS_DIR}/check_{check["id"]}.json", "w") as fp:
                fp.write(json.dumps(check_data))

        # console.print(check_data)
        if "http" in check_data["type"]:
            url = f"type: http, {check_data['type']['http']['url']}"
        else:
            url = f"type: {','.join(check_data['type'])}"

        for key in check_data["type"].keys():
            type_counter[key] = type_counter.get(key, 0) + 1

        if "__heartbeat__" in url:
            heartbeat_count += 1

        frequency_counter[check_data["resolution"]] = frequency_counter.get(check_data["resolution"], 0) + 1
        tags = [
            "component_*" if tag["name"].startswith("component_") else tag["name"]
            for tag in check_data["tags"]
        ]
        all_tags.update(tags)

        for env in ["dev", "stage", "prod"]:
            if env in tags:
                env_counter[env] = env_counter.get(env, 0) + 1

        tags_str = ", ".join(tags)
        row = [str(check_data["id"]), check_data["name"], tags_str, str(check_data["resolution"]), url]
        table.add_row(*row)

    console.print(table)
    console.print(f"Total checks:  {len(checks)}")
    console.print(f"Use heartbeat: {heartbeat_count}")
    console.print("All tags:")
    console.print(list(sorted(all_tags)))
    console.print("Frequency count:")
    console.print(frequency_counter)
    console.print("Type count:")
    console.print(type_counter)
    console.print("Env count:")
    console.print(env_counter)


if __name__ == "__main__":
    main()
