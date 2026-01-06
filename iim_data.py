#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "click",
#     "glom",
#     "jira",
#     "python-dotenv",
#     "requests",
#     "rich",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Retrieve IIM Jira project data as csv.
"""

import csv
import json
import os
import re

import click
from dotenv import load_dotenv
from glom import glom
import jira
from jira.resources import Issue
from rich import print


DATADIR = "iim_data"


load_dotenv()


def fetch_issue_data(jira_client, issue_key):
    cache_path = os.path.join(DATADIR, f"{issue_key}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as fp:
                data = json.load(fp)
                issue = Issue(
                    options=jira_client._options,
                    session=jira_client._session,
                    raw=data,
                )
                return issue
        except Exception as exc:
            print(exc)

    issue = jira_client.issue(issue_key, expand="changelog")
    with open(cache_path, "w") as fp:
        json.dump(issue.raw, fp)
    return issue


def convert_datestamp(datestamp):
    """Drop the timezone and convert to google sheets friendly datestamp.

    2025-01-31T15:06:00.000-0500 -> 2025-01-31 15:06:00

    """
    if not datestamp:
        return datestamp

    return datestamp[0:10] + " " + datestamp[11:19]


DOC_RE = re.compile("https://docs.google.com/document/d/[0-9_A-Za-z]+/edit")


def extract_doc(incident):
    # If there is a web link, that's preferred.
    # FIXME

    # The description value is in Markdown. This value is in Markdown. If they
    # used a Jira "chip", then the Markdown contains no document link at all.
    description = glom(incident, "fields.description", default="no description")
    match = DOC_RE.search(description)
    if match is None:
        return "no doc"
    return match.group(0)


@click.command()
@click.pass_context
def iim_data(ctx):
    """
    Fetches IIM Jira project data.

    Create an API token in Jira and set these in the `.env` file:

    \b
    * JIRA_USERNAME
    * JIRA_PASSWORD
    * JIRA_URL
    """

    if not os.path.exists(DATADIR):
        os.mkdir(DATADIR)

    username = os.environ["JIRA_USERNAME"].strip()
    password = os.environ["JIRA_PASSWORD"].strip()
    url = os.environ["JIRA_URL"].strip()

    jira_client = jira.JIRA(server=url, basic_auth=(username, password))

    issue_data = []
    consecutive_errors = 0
    i = 1
    click.echo("Fetching Jira data for IIM...")
    while consecutive_errors < 20:
        try:
            issue_data.append(fetch_issue_data(jira_client, f"IIM-{i}"))
            consecutive_errors = 0
        except jira.exceptions.JIRAError as exc:
            consecutive_errors += 1
            click.echo(f"Error: IIM-{i}: {exc.status_code}: {exc.text}")
        i += 1

    with open("iim_incidents.csv", "w") as fp:
        csv_file = csv.writer(fp)

        # NOTE(willkg: "issuelinks" holds link data
        csv_file.writerow(
            [
                "key",
                "summary",
                "incident doc",
                "severity customfield_10319",
                "status",
                "detected customfield_12881",
                "services customfield_12880",
                "detected",
                "alerted",
                "acknowledged",
                "responded",
                "mitigated",
                "resolved",
                "# actions",
                "# completed actions",
            ]
        )

        # cf_map = {
        #   "services": "customfield_12880",
        #   "detection_method": "customfield_12881",
        #   "severity": "customfield_10319",
        #   "time_detected": "customfield_12882",
        #   "time_alerted": "customfield_12883",
        #   "time_acknowledge": "customfield_12884",
        #   "time_responded": "customfield_12885",
        #   "time_mitigated": "customfield_12886",
        #   "time_resolved": "customfield_12887"
        # }
        for issue in issue_data:
            if glom(issue, "fields.issuetype.name", default="") != "Incident":
               continue

            csv_file.writerow(
                [
                    url + "browse/" + glom(issue, "key"),
                    glom(issue, "fields.summary", default="no summary"),
                    extract_doc(issue),
                    # severity
                    glom(issue, "fields.customfield_10319.value", default="no severity"),
                    glom(issue, "fields.status.name", default="no status"),
                    # detected
                    glom(issue, "fields.customfield_12881.value", default="no detection method"),
                    # services
                    ", ".join(
                        [
                            service.value
                            for service in (glom(issue, "fields.customfield_12880", default=None) or [])
                        ]
                    ),
                    # detected
                    convert_datestamp(glom(issue, "fields.customfield_12882", default="")),
                    # alerted
                    convert_datestamp(glom(issue, "fields.customfield_12883", default="")),
                    # acknowledged
                    convert_datestamp(glom(issue, "fields.customfield_12884", default="")),
                    # responded
                    convert_datestamp(glom(issue, "fields.customfield_12885", default="")),
                    # mitigated
                    convert_datestamp(glom(issue, "fields.customfield_12886", default="")),
                    # resolved
                    convert_datestamp(glom(issue, "fields.customfield_12887", default="")),
                    # number of actions
                    # FIXME(willkg): figure this out
                    "",
                    # number of completed actions
                    # FIXME(willkg): figure this out
                    "",
                ]
            )


if __name__ == "__main__":
    iim_data()
