#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "arrow",
#     "click",
#     "glom",
#     "python-dotenv",
#     "requests",
#     "rich",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Computes a list of recently resolved incidents and a list of active incidents
based on Jira data from `iim_data.py`.
"""

import json
import os
import urllib.parse

import arrow
import click
from dotenv import load_dotenv
from glom import glom
import rich


DATADIR = "iim_data"


load_dotenv()


def convert_datestamp(datestamp):
    """Drop the timezone and convert to google sheets friendly datestamp.

    2025-01-31T15:06:00.000-0500 -> 2025-01-31 15:06:00

    """
    if not datestamp:
        return datestamp

    return datestamp[0:10] + " " + datestamp[11:19]


def extract_doc(incident: dict):
    def is_doc(url):
        return url and url.startswith("https://docs.google.com/document")

    description = glom(incident, "fields.description", default={})

    # Do a depth-first search with the assumption that the first doc listed is
    # the incident report
    content_nodes = description.get("content", [])
    while content_nodes:
        node = content_nodes.pop(0)
        if node["type"] == "inlineCard" and is_doc(node["attrs"]["url"]):
            return node["attrs"]["url"]
        if node["type"] == "text":
            marks = node.get("marks", [])
            for mark in marks:
                if mark["type"] != "link":
                    continue
                if is_doc(mark["attrs"]["href"]):
                    return mark["attrs"]["href"]
        content_nodes = node.get("content", []) + content_nodes

    return "no doc"


def fix_incident_data(incident):
    return {
        "key": incident["key"],
        "jira_url": f"https://mozilla-hub.atlassian.net/browse/{incident['key']}",
        "status": incident["fields"]["status"]["name"],
        "summary": incident["fields"]["summary"],
        "severity": glom(incident, "fields.customfield_10319.value", default=None),
        "report_url": extract_doc(incident),
        "declare date": glom(incident, "fields.customfield_15087", default=None),
        "impact start": glom(incident, "fields.customfield_15191", default=None),
        "detection method": glom(incident, "fields.customfield_12881.value", default=None),
        "detected": glom(incident, "fields.customfield_12882", default=None),
        "alerted": glom(incident, "fields.customfield_12883", default=None),
        "acknowledged": glom(incident, "fields.customfield_12884", default=None),
        "responded": glom(incident, "fields.customfield_12885", default=None),
        "mitigated": glom(incident, "fields.customfield_12886", default=None),
        "resolved": glom(incident, "fields.customfield_12887", default=None),
    }


def get_arrow_time_or_none(incident, field, fieldname):
    value = glom(incident, f"fields.{field}", default="")
    if not value:
        click.echo(f"Error: {incident['key']}: has no {fieldname}: {value!r}")
    else:
        value = arrow.get(value)

    return value


def generate_jira_link(incident_keys):
    base = "https://mozilla-hub.atlassian.net/jira/software/c/projects/IIM/issues?"
    keys = ",".join(incident_keys)
    params = {
        "jql": f"project = IIM AND issuetype = Incident AND key in ({keys})"
    }
    return base + urllib.parse.urlencode(params)


@click.command()
@click.pass_context
def iim_active(ctx):
    """
    Computes a list of recently resolved incidents and a list of active
    incidents based on Jira data from `iim_data.py`.

    Create an API token in Jira and set these in the `.env` file:

    \b
    * JIRA_USERNAME
    * JIRA_PASSWORD
    * JIRA_URL
    """

    cache_path = os.path.join(DATADIR, "iim_issue_data.json")
    with open(cache_path, "r") as fp:
        incidents = json.load(fp)

    incidents = [
        fix_incident_data(incident) for incident in incidents
    ]

    # shift to last week, floor('week') gets monday, shift 4 days to friday
    two_weeks_ago = arrow.now().shift(days=-14).format("YYYY-MM-DD")

    resolved_incidents = [item for item in incidents if item["resolved"] and item["resolved"] > two_weeks_ago]
    click.echo()
    click.echo(f"# Recently resolved incidents ({len(resolved_incidents)}):")
    click.echo()
    for incident in resolved_incidents:
        rich.print(f"{incident['key']}  {incident['summary']}")
        rich.print(incident["resolved"])
        rich.print(incident["jira_url"])
        rich.print(incident["report_url"])
        click.echo()

    active_incidents = [item for item in incidents if item["status"] != "Resolved"]
    click.echo()
    click.echo(f"# Active incidents ({len(active_incidents)}):")
    click.echo()
    for incident in active_incidents:
        rich.print(f"{incident['key']}  {incident['summary']}")
        rich.print(incident["jira_url"])
        rich.print(incident["report_url"])
        click.echo()


if __name__ == "__main__":
    iim_active()
