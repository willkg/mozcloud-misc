#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "arrow",
#     "click",
#     "glom",
#     "jira",
#     "python-dotenv",
#     "requests",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Computes stats for the IIM Jira project for incidents declared during the
specified quarter.
"""

import json
import os
import statistics

import arrow
import click
from dotenv import load_dotenv
from glom import glom
import jira
from jira.resources import Issue


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


def get_arrow_time_or_none(incident, field, fieldname):
    value = glom(incident, f"fields.{field}", default="")
    if value is None:
        click.echo(f"Error: {incident.key}: has no {fieldname}: {value!r}")
    else:
        value = arrow.get(value)

    return value


@click.command()
@click.option("--csv/--no-csv", default=False)
@click.argument("year")
@click.argument("quarter")
@click.pass_context
def iim_data(ctx, csv, year, quarter):
    """
    Computes stats for the IIM Jira project for incidents declared in the
    specified quarter.

    Create an API token in Jira and set these in the `.env` file:

    \b
    * JIRA_USERNAME
    * JIRA_TOKEN
    """

    year = int(year.strip())
    quarter = int(quarter.strip())

    if quarter == 1:
        date_start = arrow.get(f"{year}-01-01 00:00:00")
        date_end = arrow.get(f"{year}-03-31 23:59:59")
    elif quarter == 2:
        date_start = arrow.get(f"{year}-04-01 00:00:00")
        date_end = arrow.get(f"{year}-06-30 23:59:59")
    elif quarter == 3:
        date_start = arrow.get(f"{year}-07-01 00:00:00")
        date_end = arrow.get(f"{year}-09-30 23:59:59")
    elif quarter == 4:
        date_start = arrow.get(f"{year}-10-01 00:00:00")
        date_end = arrow.get(f"{year}-12-31 23:59:59")
    else:
        raise ValueError("quarter must be 1, 2, 3, or 4")

    if not os.path.exists(DATADIR):
        os.mkdir(DATADIR)

    username = os.environ["JIRA_USERNAME"].strip()
    password = os.environ["JIRA_TOKEN"].strip()

    jira_client = jira.JIRA(
        server="https://mozilla-hub.atlassian.net/",
        basic_auth=(username, password),
    )

    # FIXME(willkg): rework this to be a search
    issue_data = []
    consecutive_errors = 0
    i = 1
    click.echo("Fetching Jira data for IIM...")
    while consecutive_errors < 10:
        try:
            issue = fetch_issue_data(jira_client, f"IIM-{i}")
            if glom(issue, "fields.issuetype.name", default="") == "Incident":
                issue_data.append(issue)
            consecutive_errors = 0
        except jira.exceptions.JIRAError as exc:
            consecutive_errors += 1
            click.echo(f"Error: IIM-{i}: {exc.status_code}: {exc.text}")
        i += 1


    # IIM issues declared this quarter; customfield_15087 is declare date
    incidents = []
    for issue in issue_data:
        declare_date = issue.fields.customfield_15087
        if declare_date is None:
            click.echo(f"IIM-{issue.key}: declare date is none: {declare_date!r}")
            continue

        if date_start <= arrow.get(declare_date) <= date_end:
            incidents.append(issue)

    click.echo("Determining statistics data...")

    severity_breakdown = {}
    detected_breakdown = {}
    tt_alerted = []
    tt_responded = []
    tt_mitigated = []

    # cf_map = {
    #   "impact start": "customfield_15191",
    #   "declare date": "customfield_15087",
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
    for incident in incidents:
        severity = str(glom(incident, "fields.customfield_10319"))
        detected_method = str(glom(incident, "fields.customfield_12881"))
        impact_start = get_arrow_time_or_none(incident, "customfield_15191", "impact start")
        alerted = get_arrow_time_or_none(incident, "customfield_12883", "alerted")
        responded = get_arrow_time_or_none(incident, "customfield_12885", "responded")
        mitigated = get_arrow_time_or_none(incident, "customfield_12886", "mitigated")

        # Drop items with no impact_start
        if impact_start is None:
            continue

        # Drop extreme response times
        if responded and (responded - impact_start).total_seconds() > 1800000:
            click.echo(f"Error: {incident.key} has excessive response time: {responded - impact_start}")
            continue

        severity_breakdown.setdefault(severity, []).append(incident)
        detected_breakdown.setdefault(detected_method, []).append(incident)
        if alerted is not None:
            tt_alerted.append((alerted - impact_start).total_seconds())

        if responded is not None:
            tt_responded.append((responded - impact_start).total_seconds())

        if mitigated is not None:
            tt_mitigated.append((mitigated - impact_start).total_seconds())

    # Convert seconds to minutes
    tt_alerted = [elem / 60 for elem in tt_alerted]
    tt_responded = [elem / 60 for elem in tt_responded]
    tt_mitigated = [elem / 60 for elem in tt_mitigated]

    # click.echo(f"alerted: {sum(tt_alerted)}  {[int(elem) for elem in tt_alerted]}")
    # click.echo(f"responded: {sum(tt_responded)}  {[int(elem) for elem in tt_responded]}")
    # click.echo(f"mitigated: {sum(tt_mitigated)}  {[int(elem) for elem in tt_mitigated]}")

    click.echo(f"{date_start} to {date_end}")
    click.echo(f"Number incidents: {len(incidents)}")
    click.echo("By severity:")
    for key, val in sorted(severity_breakdown.items()):
        click.echo(f"   {key}: {len(val)}  {len(val) / len(incidents) * 100:2.2f}")
    click.echo("By detected method:")
    for key, val in sorted(detected_breakdown.items()):
        click.echo(f"   {key}: {len(val)}  {len(val) / len(incidents) * 100:2.2f}")
    alerted_mins = statistics.mean(tt_alerted)
    click.echo(f"MTT alerted:      {alerted_mins:.2f} mins  {alerted_mins / 60:.2f} hrs")
    responded_mins = statistics.mean(tt_responded)
    click.echo(
        f"MTT responded:    {responded_mins:.2f} mins  {responded_mins / 60:.2f} hrs")
    mitigated_mins = statistics.mean(tt_mitigated)
    click.echo(
        f"MTT mitigated:    {mitigated_mins:.2f} mins  {mitigated_mins / 60:.2f} hrs"
    )

    if csv:
        with open("iim_incidents.csv", "w") as fp:
            for incident in incidents:
                impact_start = get_arrow_time_or_none(incident, "customfield_15191", "impact start")
                alerted = get_arrow_time_or_none(incident, "customfield_12883", "alerted")
                responded = get_arrow_time_or_none(incident, "customfield_12885", "responded")
                mitigated = get_arrow_time_or_none(incident, "customfield_12886", "mitigated")

                if impact_start is None:
                    continue

                cols = [
                    f"IIM-{incident.key}",
                    str(impact_start),
                    str(alerted),
                    str(responded),
                    # in minutes
                    responded and "%.2f" % ((responded - impact_start).total_seconds() / 60) or "",
                    str(mitigated),
                    # in minutes
                    mitigated and "%.2f" % ((mitigated - impact_start).total_seconds() / 60) or "",
                ]

                fp.write(",".join(cols) + "\n")


if __name__ == "__main__":
    iim_data()
