#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "arrow",
#     "click",
#     "glom",
#     "python-dotenv",
#     "requests",
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
from typing import List, Dict, Optional, Union

import arrow
import click
from dotenv import load_dotenv
from glom import glom
import requests
from requests.auth import HTTPBasicAuth


DATADIR = "iim_data"


load_dotenv()


def get_timestamp(issue, field, fieldname):
    value = glom(issue, f"fields.{field}", default="")
    if value is None:
        click.echo(f"Error: {issue['key']}: has no {fieldname}: {value!r}")
    else:
        value = arrow.get(value)

    return value


def convert_datestamp(datestamp: str):
    """Drop the timezone and convert to google sheets friendly datestamp.

    2025-01-31T15:06:00.000-0500 -> 2025-01-31 15:06:00

    """
    if not datestamp:
        return datestamp

    return datestamp[0:10] + " " + datestamp[11:19]


def get_all_issues_for_project(
    jira_base_url: str,
    project_key: str,
    username: str,
    token: str,
    max_results: int = 100,
    fields: Union[str, List[str]] = "*all",
) -> List[Dict]:
    """
    Fetch all Jira issues for a given project key (Jira Cloud) using the
    enhanced JQL search endpoint: GET /rest/api/3/search/jql.

    Returns: list of issue JSON objects.
    """
    issues: List[Dict] = []
    next_page_token: Optional[str] = None

    auth = HTTPBasicAuth(username, token)
    headers = {"Accept": "application/json"}

    # Bounded JQL is recommended/required for some newer endpoints; ordering helps keep it stable.
    jql = f'project = "{project_key}" and issueType = "Incident" ORDER BY created ASC'

    while True:
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields,
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        resp = requests.get(
            f"{jira_base_url.rstrip('/')}/rest/api/3/search/jql",
            headers=headers,
            params=params,
            auth=auth,
            timeout=30,
        )
        resp.raise_for_status()

        data = resp.json()
        issues.extend(data.get("issues", []))

        # Enhanced search pagination: stop when isLast == True, otherwise follow nextPageToken.
        if data.get("isLast") is True:
            break

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            # Defensive: if Jira doesn't provide a token but also didn't say it's last, stop to avoid looping.
            break

    return issues


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


@click.command()
@click.option("--cache/--no-cache", default=True)
@click.pass_context
def iim_data(ctx: click.Context, cache: bool):
    """
    Fetches IIM Jira project data.

    Create an API token in Jira and set these in the `.env` file:

    \b
    * JIRA_USERNAME
    * JIRA_TOKEN
    * JIRA_URL
    """

    if not os.path.exists(DATADIR):
        os.mkdir(DATADIR)

    username = os.environ["JIRA_USERNAME"].strip()
    token = os.environ["JIRA_TOKEN"].strip()
    url = os.environ["JIRA_URL"].strip().rstrip("/")
    issue_data = []

    cache_path = os.path.join(DATADIR, "iim_issue_data.json")
    if cache:
        if os.path.exists(cache_path):
            with open(cache_path, "r") as fp:
                issue_data = json.load(fp)

    if not issue_data:
        issue_data = get_all_issues_for_project(
            jira_base_url=url,
            project_key="IIM",
            username=username,
            token=token,
        )

    # Always dump to cache
    with open(cache_path, "w") as fp:
        json.dump(issue_data, fp)

    def calc_tt(value, impact_start):
        if not value or not impact_start:
            return None
        return (value - impact_start).total_seconds() / 60

    # Normalize and fix data, calculate additional fields
    for issue in issue_data:
        impact_start = get_timestamp(issue, "customfield_18693", "impact start")

        declared = get_timestamp(issue, "customfield_18692", "declared")
        if declared and declared > arrow.get("2025-09-15"):
            issue["tt-dec"] = calc_tt(declared, impact_start)
        else:
            issue["tt-dec"] = ""
        detected = get_timestamp(issue, "customfield_18694", "detected")
        issue["tt-det"] = calc_tt(detected, impact_start)
        alerted = get_timestamp(issue, "customfield_18695", "alerted")
        issue["tt-alt"] = calc_tt(alerted, impact_start)
        responded = get_timestamp(issue, "customfield_18697", "responded")
        issue["tt-res"] = calc_tt(responded, impact_start)
        mitigated = get_timestamp(issue, "customfield_18696", "mitigated")
        issue["tt-mit"] = calc_tt(mitigated, impact_start)

    # Write data to CSV
    with open("iim_incidents.csv", "w") as fp:
        csv_file = csv.writer(fp)

        # NOTE(willkg: "issuelinks" holds link data
        csv_file.writerow(
            [
                "key",
                "summary",
                "incident doc",
                "severity (10319)",
                "status",
                "detection method (12881)",
                "entities (18555)",
                "time declared (18692)",
                "tt-dec",
                "impact start (18693)",
                "time detected (18694)",
                "tt-det",
                "time alerted (18695)",
                "tt-alt",
                "time acknowledged (18696)",
                "time responded (18697)",
                "tt-res",
                "time mitigated (18698)",
                "tt-mit",
                "time resolved (18699)",
                "# actions",
                "# completed actions",
            ]
        )

        for issue in issue_data:
            if glom(issue, "fields.issuetype.name", default="") != "Incident":
                continue

            csv_file.writerow(
                [
                    url + "/browse/" + glom(issue, "key"),
                    glom(issue, "fields.summary", default="no summary"),
                    extract_doc(issue),
                    # severity
                    glom(
                        issue, "fields.customfield_10319.value", default="no severity"
                    ),
                    glom(issue, "fields.status.name", default="no status"),
                    # detection_method
                    glom(
                        issue,
                        "fields.customfield_12881.value",
                        default="no detection method",
                    ),
                    # entities
                    glom(issue, "fields.customfield_18555", default=None),
                    # declared
                    convert_datestamp(
                        glom(issue, "fields.customfield_18692", default="")
                    ),
                    issue["tt-dec"],
                    # impact start
                    convert_datestamp(
                        glom(issue, "fields.customfield_18693", default=""),
                    ),
                    # detected
                    convert_datestamp(
                        glom(issue, "fields.customfield_18694", default="")
                    ),
                    issue["tt-det"],
                    # alerted
                    convert_datestamp(
                        glom(issue, "fields.customfield_18695", default="")
                    ),
                    issue["tt-alt"],
                    # acknowledged
                    convert_datestamp(
                        glom(issue, "fields.customfield_18696", default="")
                    ),
                    # responded
                    convert_datestamp(
                        glom(issue, "fields.customfield_18697", default="")
                    ),
                    issue["tt-res"],
                    # mitigated
                    convert_datestamp(
                        glom(issue, "fields.customfield_18698", default="")
                    ),
                    issue["tt-mit"],
                    # resolved
                    convert_datestamp(
                        glom(issue, "fields.customfield_18699", default="")
                    ),
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
