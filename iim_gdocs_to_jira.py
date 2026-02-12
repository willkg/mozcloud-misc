#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "click",
#     "marko",
#     "python-dotenv",
#     "requests",
#     "rich",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Convert incident reports (as markdown) to field data and push to Jira.
"""

import copy
import os
import re
from typing import Dict

import click
from dotenv import load_dotenv
import marko
import requests
from requests.auth import HTTPBasicAuth
import rich
from rich.table import Table


load_dotenv()


DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
DATETIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
JIRA_ISSUE_RE = re.compile(r"(IIM\-\d+)")


def extract_jira_issue(value):
    """Extract Jira issue key"""
    match = JIRA_ISSUE_RE.search(value)
    if match:
        return match[0]
    raise Exception(f"{value!r} has no jira issue key")


def extract_datestamp(value):
    """Extract datetime or date and return in iso8601 format for UTC"""
    match = DATETIME_RE.search(value)
    if match:
        return match[0][0:10] + "T" + match[0][11:16] + ":00.000-0000"
    match = DATE_RE.search(value)
    if match:
        return match[0] + "T00:00:00.000-0000"
    return None


def get_issue_data(
    jira_base_url: str,
    username: str,
    password: str,
    issue_key: str,
) -> Dict:
    """
    Fetches data for the Jira incident issue specified by incident_key.
    """

    auth = HTTPBasicAuth(username, password)
    headers = {"Accept": "application/json"}

    url = f"{jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}"

    response = requests.get(
        url,
        auth=auth,
        headers=headers,
        timeout=30,
    )

    # Raise an exception for 4xx/5xx responses
    response.raise_for_status()

    return response.json()


def update_jira_issue(
    jira_base_url: str,
    username: str,
    password: str,
    issue_key: str,
    updated_fields: dict,
) -> None:
    """
    Update a Jira issue with new field data.

    :raises requests.HTTPError: if the request fails
    """
    url = f"{jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}"

    auth = HTTPBasicAuth(username, password)
    headers = {"Accept": "application/json"}
    payload = {
        "fields": updated_fields,
    }

    response = requests.put(
        url,
        auth=auth,
        headers=headers,
        json=payload,
        timeout=30,
    )

    # Jira returns 204 No Content on success
    if response.status_code not in (200, 204):
        response.raise_for_status()


# incident report field header -> data field
METADATA_LABEL_TO_FIELD = {
    "incident title": "summary",
    "incident severity": "severity",
    "jira ticket/bug number": "issues",
    "issue detected via": "detection method",
    "current status": "status",
    "time of first impact": "impact start",
    "time detected": "detected",
    "time alerted": "alerted",
    "time acknowledged": "acknowledged",
    "time responded/engaged": "responded",
    "time mitigated (repaired)": "mitigated",
    "time resolved": "resolved",
}


DEFAULT_DATA = {
    "key": None,
    "summary": None,
    "severity": None,
    "detection method": None,
    "status": None,
    # timestamps in UTC in YYYY-MM-DD HH:MM format
    "impact start": None,
    "detected": None,
    "alerted": None,
    "acknowledged": None,
    "responded": None,
    "mitigated": None,
    "resolved": None,
}


def is_header(token):
    return isinstance(token, marko.block.Heading)


def is_table(token):
    return (
        isinstance(token, marko.block.Paragraph)
        and token.children
        and token.children[0].children
        and isinstance(token.children[0].children, str)
        and token.children[0].children.startswith("|")
    )


def get_text(token):
    text = []
    if isinstance(
        token, (
            marko.inline.CodeSpan,
            marko.inline.LineBreak,
            marko.inline.Literal,
            marko.inline.RawText,
        )
    ):
        text.append(token.children)
    elif isinstance(token, marko.inline.Link):
        link_text = []
        for child in token.children:
            link_text.extend(get_text(child))
        text.append(f"[{''.join(link_text) or 'Link'}]({token.dest})")
    else:
        for child in token.children:
            text.extend(get_text(child))

    return "".join(text)


def md_to_dict(md):
    data = copy.deepcopy(DEFAULT_DATA)

    metadata_table = None
    action_items_table = None

    ast = marko.Markdown().parse(md)
    tokens = ast.children
    while tokens:
        token = tokens.pop(0)
        if is_header(token):
            # <Heading children=[<RawText children=TEXT>...]>
            text = token.children[0].children
            if text.startswith("Incident: "):
                data["summary"] = text.strip()[10:]
                while tokens:
                    token = tokens.pop(0)
                    if is_table(token):
                        metadata_table = token
                        break

            if text.startswith("Postmortem Action Items"):
                while tokens:
                    token = tokens.pop(0)
                    if is_table(token):
                        action_items_table = token
                        break

    # Parse metadata table and update data
    #
    # NOTE(willkg): the AST from the Markdown has this as a stream of tokens,
    # so we convert that back into the Markdown text and then re-tokenize it
    # because it's easier to deal with that way even if it is a bit silly
    metadata_table_text = get_text(metadata_table)
    data.update(metadata_table_to_dict(metadata_table_text))

    # FIXME(willkg): parse action_items_table and update data
    return data


def metadata_table_to_dict(md):
    # Convert Markdown text table to Python dict
    md_table = {}
    for line in md.splitlines():
        line = line.strip()
        if not line:
            continue
        line = line.split("|")
        label = line[1].lower().replace("*", "").strip()
        for key, val in METADATA_LABEL_TO_FIELD.items():
            if key in label:
                field = val
                break
        else:
            continue
        value = line[2]

        md_table[field] = value

    data = {}

    # Jira issue key
    data["key"] = extract_jira_issue(md_table["issues"])

    # Status
    data["status"] = md_table["status"].strip()

    # Severity fields.customfield_10319
    if "S1 - Critical" in md_table["severity"]:
        data["severity"] = {"value": "S1"}
    elif "S2 - High" in md_table["severity"]:
        data["severity"] = {"value": "S2"}
    elif "S3 - Medium" in md_table["severity"]:
        data["severity"] = {"value": "S3"}
    elif "S4 - Low" in md_table["severity"]:
        data["severity"] = {"value": "S4"}
    else:
        data["severity"] = None

    # Update impact start fields.custom_field_15191
    data["impact start"] = extract_datestamp(md_table["impact start"])

    # Update detection method
    if "Manual/Human" in md_table["detection method"]:
        data["detection method"] = {"value": "Manual"}
    elif "Automated Alert" in md_table["detection method"]:
        data["detection method"] = {"value": "Automation"}
    else:
        data["detection method"] = None

    # TODO: update services
    # Update detected timestamp fields.customfield_12882
    data["detected"] = extract_datestamp(md_table["detected"])
    # Update alerted timestamp fields.customfield_12883
    data["alerted"] = extract_datestamp(md_table["alerted"])
    # Update acknowledged timestamp fields.customfield_12884
    data["acknowledged"] = extract_datestamp(md_table["acknowledged"])
    # Update responded timestamp fields.customfield_12885
    data["responded"] = extract_datestamp(md_table["responded"])
    # Update mitigated timestamp fields.customfield_12886
    data["mitigated"] = extract_datestamp(md_table["mitigated"])
    # Update resolved timestamp fields.customfield_12887
    data["resolved"] = extract_datestamp(md_table["resolved"])

    return data


@click.command()
@click.option("--commit/--no-commit", default=False)
@click.argument("docs", nargs=-1)
@click.pass_context
def iim_google_docs_to_jira(ctx: click.Context, commit: bool, docs: tuple[str, ...]):
    """
    Prompts user for google doc metadata as markdown. Parses the markdown and
    extracts updated metadata and issue key. Pushes information to Jira.

    Create an API token in Jira and set these in the `.env` file:

    \b
    * JIRA_USERNAME
    * JIRA_PASSWORD
    * JIRA_URL
    """
    username = os.environ["JIRA_USERNAME"].strip()
    password = os.environ["JIRA_PASSWORD"].strip()
    url = os.environ["JIRA_URL"].strip().rstrip("/")

    if not docs:
        raise click.BadParameter(
            "Requires at least one doc",
            ctx=ctx,
            param_hint="docs",
        )

    for fn in docs:
        click.echo()
        with open(fn, "r") as fp:
            md_data = fp.read()
            first_line = md_data.splitlines()[0]

            if not first_line.startswith("# Incident"):
                click.echo(f"{fn} is not an incident report. Skipping.")
                continue

            click.echo(f"Parsing {fn}...")

            new_data = md_to_dict(md_data)

            incident_key = new_data["key"]

            incident = get_issue_data(
                jira_base_url=url,
                username=username,
                password=password,
                issue_key=incident_key,
            )

            updated_fields = {}

            # Update summary
            updated_fields["summary"] = new_data["summary"]
            if incident["fields"]["customfield_15087"]:
                updated_fields["summary"] = (
                    updated_fields["summary"] +
                    f" ({incident['fields']['customfield_15087']})"
                )
            # Update severity fields.customfield_10319
            updated_fields["customfield_10319"] = new_data["severity"]
            # Update impact start fields.customfield_15191
            updated_fields["customfield_15191"] = new_data["impact start"]
            # Update detection method fields.customfield_12881
            updated_fields["customfield_12881"] = new_data["detection method"]
            # Update detected timestamp fields.customfield_12882
            updated_fields["customfield_12882"] = new_data["detected"]
            # Update alerted timestamp fields.customfield_12883
            updated_fields["customfield_12883"] = new_data["alerted"]
            # Update acknowledged timestamp fields.customfield_12884
            updated_fields["customfield_12884"] = new_data["acknowledged"]
            # Update responded timestamp fields.customfield_12885
            updated_fields["customfield_12885"] = new_data["responded"]
            # Update mitigated timestamp fields.customfield_12886
            updated_fields["customfield_12886"] = new_data["mitigated"]
            # Update resolved timestamp fields.customfield_12887
            updated_fields["customfield_12887"] = new_data["resolved"]

            # TODO: Update status -- have to do this with a transition
            # TODO: Update services
            # TODO: Update post-mortem actions -- not in metadata

            click.echo()
            click.echo("Data to update:")
            click.echo("Jira: " + f"https://mozilla-hub.atlassian.net/browse/{incident['key']}")
            click.echo("Status: " + incident["fields"]["status"]["name"])

            table = Table()
            table.add_column("field")
            table.add_column("current")
            table.add_column("new")

            for name, field in (
                ("summary", "summary"),
                ("severity", "customfield_10319"),
                ("impact start", "customfield_15191"),
                ("detection method", "customfield_12881"),
                ("detected (ts)", "customfield_12882"),
                ("alerted (ts)", "customfield_12883"),
                ("acknowledged (ts)", "customfield_12884"),
                ("responded (ts)", "customfield_12885"),
                ("mitigated (ts)", "customfield_12886"),
                ("resolved (ts)", "customfield_12887"),
            ):
                if name in ("severity", "detection method"):
                    current_value = {"value": incident["fields"][field]["value"]}
                else:
                    current_value = incident["fields"][field]
                table.add_row(name, str(current_value), str(updated_fields[field]))

            rich.print(table)
            click.echo()
            click.echo("Note: Jira returns timestamps in local timezone.")
            click.echo()

            if not commit:
                click.echo("Not committing to Jira. Pass --commit to commit.")
            else:
                click.echo("Ok to commit?")
                input()
                click.echo("Committing to Jira ...")
                update_jira_issue(
                    jira_base_url=url,
                    username=username,
                    password=password,
                    issue_key=incident_key,
                    updated_fields=updated_fields,
                )

    click.echo("Done!")


if __name__ == "__main__":
    iim_google_docs_to_jira()
