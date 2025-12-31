#!/usr/bin/env python
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "arrow",
#     "click",
#     "jira",
#     "python-dotenv",
#     "requests",
# ]
# ///

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Computes stats for the SREIN Jira project for the specified quarter.
"""

import json
import os
import statistics

import arrow
import click
from dotenv import load_dotenv
import jira
from jira.resources import Issue


DATADIR = "srein_data"
CLOUDENG_TEAM = [
    "Brandon Patterson",
    "Brandon Wells",
    "Brett Kochendorfer",
    "Chris Valaas",
    "Dustin Lactin",
    "Hamid Tahsildoost",
    "Hristo Ganchev",
    "Jon Buckley",
    "Mikaël Ducharme",
    "Nate Tade",
    "Paul Hammer",
    "Rachel Pohl",
    "Robert Müller",
    "Steven Prokopienko",
    "Wei Zhou",
    "Wesley Dawson",
    "William Kahn-Greene",
]


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


def percentile(values, nth):
    values = list(sorted(values))
    index = int(nth * len(values) / 100)
    return values[index]


@click.command()
@click.argument("year")
@click.argument("quarter")
@click.pass_context
def srein_statistics(ctx, year, quarter):
    """
    Computes stats for the SREIN Jira project for the specified quarter.

    Create an API token in Jira and set these in the `.env` file:

    \b
    * JIRA_USERNAME
    * JIRA_TOKEN
    * JIRA_URL
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
    url = os.environ["JIRA_URL"].strip()

    jira_client = jira.JIRA(server=url, basic_auth=(username, password))

    # NOTE(willkg): This is goofy. There isn't a good way to get a list of all
    # the issues. It's complicated by:
    #
    # 1. The search_issues() thing only gives me issues _currently_ in the
    #    project, but not things that got moved out.
    # 2. I may not have permission to see an issue.
    # 3. The API returns 404 if the issue doesn't exist as well as if I don't
    #    have permissions, so I can't count on it to know when there are no
    #    more issues to look at
    #
    # Thus, this loops until we have N consecutive 404s and then stops.
    issue_data = []
    consecutive_errors = 0
    i = 1
    click.echo("Fetching Jira data for SREIN...")
    while consecutive_errors < 20:
        try:
            issue_data.append(fetch_issue_data(jira_client, f"SREIN-{i}"))
            consecutive_errors = 0
        except jira.exceptions.JIRAError as exc:
            consecutive_errors += 1
            click.echo(f"Error: SREIN-{i}: {exc.status_code}: {exc.text}")
        i += 1

    # SREIN issues created or updated this quarter
    cu_issue_data = [
        issue
        for issue in issue_data
        if (
            date_start <= arrow.get(issue.fields.created) <= date_end
            or date_start <= arrow.get(issue.fields.updated) <= date_end
        )
    ]

    # SREIN issues created this quarter
    c_issue_data = [
        issue
        for issue in issue_data
        if date_start <= arrow.get(issue.fields.created) <= date_end
    ]

    click.echo()
    click.echo("Checking issues reported by CloudEng...")
    for issue in cu_issue_data:
        reporter = issue.fields.reporter.displayName
        if reporter in CLOUDENG_TEAM:
            click.echo(
                f"CloudEng reporter: {reporter}: "
                + f"{issue.key} - "
                + f"{issue.fields.summary} - "
                + f"{issue.permalink()}"
            )

    click.echo()
    click.echo("Determining statistics data...")
    created = 0
    created_or_updated = 0
    unresolved = 0
    unresponded = 0
    reporters = set()
    time_to_resolution = []
    time_to_response = []
    routed_counter = {}
    resolution_breakdown = {}
    for issue in cu_issue_data:
        # We want statistics for customers only
        reporter = issue.fields.reporter.displayName
        if reporter in CLOUDENG_TEAM:
            continue

        if date_start <= arrow.get(issue.fields.created) <= date_end:
            created += 1
        created_or_updated += 1

        reporters.add(reporter)

        # Capture routing breakdown
        project = issue.fields.project.key
        routed_counter.setdefault(project, []).append(1)

        if issue.fields.resolution is None or issue.fields.resolution.name != "Done":
            # Capture number of uncompleted
            unresolved += 1
        else:
            # Capture time to resolution
            created_time = arrow.get(issue.fields.created)
            # maybe statuscategorychangedate, resolutiondate
            resolutiondate_time = arrow.get(issue.fields.resolutiondate)
            time_to_resolution.append((resolutiondate_time - created_time).days)
            resolution_breakdown.setdefault(
                issue.fields.statusCategory.name, []
            ).append(1)

        # Capture time to response which is the delta between created and list
        # item in the changelog not from reporter (it's DESC) or automation
        reporter = issue.fields.reporter.accountId
        created_time = arrow.get(issue.fields.created)
        for hist in reversed(issue.changelog.histories):
            fields = " ".join([item.field for item in hist.items])
            # Ignore history entries where the reporter sets something other
            # than "status" or "project";
            # Ignore history entries from automation
            if (
                hist.author.accountId == reporter
                and "status" not in fields
                and "project" not in fields
            ) or (
                hist.author.displayName.startswith("Automation")
                or hist.author.displayName.startswith("ScriptRunner")
            ):
                continue
            time_to_response.append((arrow.get(hist.created) - created_time).days)
            break
        else:
            click.echo(
                f"Unresponded: {issue.key}: {issue.fields.summary} - {issue.permalink()}"
            )
            unresponded += 1

    # Print SREIN stats
    click.echo()
    click.echo(f"Statistics: {year}q{quarter}")
    click.echo(f"* created or updated count (all): {len(cu_issue_data)}")
    click.echo(f"* created issues (all): {len(c_issue_data)}")
    click.echo(f"  * customers: {created}")
    click.echo(f"  * internal: {len(c_issue_data) - created}")
    click.echo(f"* unresolved issues (customer): {unresolved}")
    click.echo(f"* number of reporters (customer): {len(reporters)}")

    click.echo("* first response (customer):")
    click.echo(f"  * unresponded: {unresponded}")
    click.echo(f"  * mean time: {statistics.mean(time_to_response):2.2f} days")
    click.echo(f"  * 90th-%: {percentile(time_to_response, 90)} days")
    click.echo(f"  * max time: {max(time_to_response)} days")

    click.echo("* resolution (customer):")
    click.echo(f"  * mean time: {statistics.mean(time_to_resolution):2.2f} days")
    click.echo(f"  * 90th-%: {percentile(time_to_resolution, 90)} days")
    click.echo(f"  * max time: {max(time_to_resolution)} days")
    click.echo("  * breakdown:")
    for key, res in resolution_breakdown.items():
        click.echo(f"    * {key}: {len(res)}")

    click.echo("* routed breakdown (customer):")
    for key, routed in sorted(
        routed_counter.items(), key=lambda item: item[1], reverse=True
    ):
        if key == "SREIN":
            continue
        click.echo(f"  * {key}: {len(routed)}")

    # click.echo("")
    # click.echo("Reporters:")
    # for reporter in reporters:
    #     click.echo(f"  * {reporter}")

    # TODO: calculate SREIN statistics
    # - mean time in “needs clarification” state


if __name__ == "__main__":
    srein_statistics()
