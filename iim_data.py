#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
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

import click
from dotenv import load_dotenv
from glom import glom
import requests
from requests.auth import HTTPBasicAuth


DATADIR = "iim_data"


load_dotenv()


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
    password: str,
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

    auth = HTTPBasicAuth(username, password)
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
    * JIRA_PASSWORD
    * JIRA_URL
    """

    if not os.path.exists(DATADIR):
        os.mkdir(DATADIR)

    username = os.environ["JIRA_USERNAME"].strip()
    password = os.environ["JIRA_PASSWORD"].strip()
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
            password=password,
        )

    # Always dump to cache
    with open(cache_path, "w") as fp:
        json.dump(issue_data, fp)

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
                    url + "/browse/" + glom(issue, "key"),
                    glom(issue, "fields.summary", default="no summary"),
                    extract_doc(issue),
                    # severity
                    glom(
                        issue, "fields.customfield_10319.value", default="no severity"
                    ),
                    glom(issue, "fields.status.name", default="no status"),
                    # detected
                    glom(
                        issue,
                        "fields.customfield_12881.value",
                        default="no detection method",
                    ),
                    # services
                    ", ".join(
                        [
                            service["value"]
                            for service in (
                                glom(issue, "fields.customfield_12880", default=None)
                                or []
                            )
                        ]
                    ),
                    # detected
                    convert_datestamp(
                        glom(issue, "fields.customfield_12882", default="")
                    ),
                    # alerted
                    convert_datestamp(
                        glom(issue, "fields.customfield_12883", default="")
                    ),
                    # acknowledged
                    convert_datestamp(
                        glom(issue, "fields.customfield_12884", default="")
                    ),
                    # responded
                    convert_datestamp(
                        glom(issue, "fields.customfield_12885", default="")
                    ),
                    # mitigated
                    convert_datestamp(
                        glom(issue, "fields.customfield_12886", default="")
                    ),
                    # resolved
                    convert_datestamp(
                        glom(issue, "fields.customfield_12887", default="")
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
