#!/usr/bin/env python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "rich",
#     "click",
# ]
# ///

import click
from rich.console import Console
from rich.table import Table


def last_seen_sort_key(item):
    last_seen = item[2]
    num, unit = last_seen.strip().split(" ")
    num = int(num)
    if unit in ("year", "years"):
        num = num * 365 * 24 * 60
    elif unit in ("month", "months"):
        num = num * 30 * 24 * 60
    elif unit in ("day", "days"):
        num = num * 24 * 60
    elif unit in ("hour", "hours"):
        num = num * 60
    return num


@click.command
@click.pass_context
def main(ctx):
    with open("user_list.tsv", "r") as fp:
        lines = fp.readlines()


    data = [line.strip().split("\t") for line in lines]

    table = Table()
    table.add_column("email")
    table.add_column("name")
    table.add_column("last seen")
    table.add_column("old?")

    rows = []
    for item in data:
        row = [item[0], item[2], item[3]]

        # If last seen is measured in years, then it's been more than 365 days
        # since the person last logged in
        if "year" in item[3]:
            row.append("yes")
        else:
            row.append("")

        rows.append(row)

    console = Console()

    console.print(f"Total rows: {len(rows)}")
    rows = [row for row in rows if row[3] != "yes"]
    console.print(f"Seen in last year: {len(rows)}")

    for row in sorted(rows, key=last_seen_sort_key, reverse=True):
        table.add_row(*row)

    console.print(table)

    for row in rows:
        console.print(row[0])


if __name__ == "__main__":
    main()
