#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "arrow",
#     "click",
#     "css_inline",
#     "glom",
#     "jinja2",
#     "python-dotenv",
#     "requests",
#     "rich",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Computes a weekly report for incidents.
"""

import json
import os

import arrow
import click
import css_inline
from dotenv import load_dotenv
from glom import glom
from jinja2 import Environment, FileSystemLoader, select_autoescape

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


@click.command()
@click.pass_context
def iim_weekly_report(ctx):
    """
    Computes a weekly report based on Jira data. Make sure to update the data
    in Jira and then run `iim_data.py` before running the report.

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
    last_friday = arrow.now().shift(weeks=-1).floor('week').shift(days=4).format('YYYY-MM-DD')
    this_friday = arrow.now().floor('week').shift(days=4).format('YYYY-MM-DD')

    click.echo(f"From: {last_friday} to {this_friday}")
    new_incidents = [
        incident for incident in incidents
        if (
            incident["declare date"][0:11] > last_friday
            and incident["declare date"][0:11] <= this_friday
        )
    ]

    severity_breakdown = {}
    for item in new_incidents:
        severity_breakdown[item["severity"]] = severity_breakdown.get(item["severity"], 0) + 1

    active_incidents = [incident for incident in incidents if incident["status"] != "Resolved"]

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape()
    )

    template = env.get_template("weekly_report.html")
    html = template.render(
        title=f"Weekly Incident Report: {this_friday}",
        this_friday=this_friday,
        last_friday=last_friday,
        num_incidents=len(new_incidents),
        num_s1_incidents=severity_breakdown.get("S1", 0),
        num_s2_incidents=severity_breakdown.get("S2", 0),
        num_s3_incidents=severity_breakdown.get("S3", 0),
        num_s4_incidents=severity_breakdown.get("S4", 0),
        new_incidents=new_incidents,
        active_incidents=active_incidents,
    )
    inliner = css_inline.CSSInliner()
    fixed_html = inliner.inline(html)

    fn = f"weekly_incident_reports/report_{last_friday.format('YYYY-MM-DD').replace('-', '')}.html"
    with open(fn, "w") as fp:
        fp.write(fixed_html)

    click.echo(f"Report written to: {fn}")


if __name__ == "__main__":
    iim_weekly_report()
