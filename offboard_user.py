#!/usr/bin/env python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "grafana_client",
#     "python-dotenv",
#     "requests",
#     "rich",
# ]
# ///

"""
Usage: uv run offboard_user.py [EMAILPREFIX]

Goes through and lists which accounts that person owns across observability
services.
"""

import os

import click
from dotenv import load_dotenv
from grafana_client import GrafanaApi, TokenAuth
import requests


load_dotenv()


YARDSTICK_API_TOKEN = os.getenv("YARDSTICK_API_TOKEN")

SENTRY_API_TOKEN = os.environ["SENTRY_API_TOKEN"]

NEWRELIC_API_TOKEN_CORPORATION_PRIMARY = os.environ["NEWRELIC_API_TOKEN_CORPORATION_PRIMARY"]


class GrafanaData:
    def __init__(self, url, token):
        self.url = url
        self.token = token

    def get_user_count(self):
        grafana = GrafanaApi.from_url(url=self.url, credential=TokenAuth(token=self.token))
        users = grafana.client.GET("/org/users")
        return len(users)

    def _get_teams_for_user(self, user_id):
        # FIXME(willkg): can't do this with a service account token--it
        # requires users:read which service account tokens don't have. there
        # doesn't seem to be a way to get the list of teams a user belongs to
        # with a service account token.
        grafana = GrafanaApi.from_url(url=self.url, credential=TokenAuth(token=self.token))
        teams = grafana.client.GET(f"/users/{user_id}/teams")
        return [team["name"] for team in teams]

    def get_matches(self, pattern):
        grafana = GrafanaApi.from_url(url=self.url, credential=TokenAuth(token=self.token))
        users = grafana.client.GET("/org/users")

        matched_users = []
        for user in users:
            if pattern in user["email"].lower():
                matched_users.append(
                    {
                        "account": user["email"],
                        # FIXME(willkg): "teams": self._get_teams_for_user(user["userId"]),
                        "teams": [],
                    }
                )

        return matched_users


class SentryData:
    def __init__(self, url, token):
        self.baseurl = url
        self.token = token

    def _get_paged_results(self, url, headers):
        has_more = True
        results = []

        # Results are paginated per https://docs.sentry.io/api/pagination/
        while has_more:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()

            results.extend(resp.json())

            link_header_next = resp.links["next"]
            has_more = (
                link_header_next["rel"] == "next"
                and link_header_next["results"] == "true"
            )
            url = link_header_next["url"]

        return results

    def get_sentry_users(self):
        """Get email addresses and teams for all active sentry users."""
        headers = {"Authorization": f"Bearer {self.token}"}

        # NOTE(willkg): There's no Sentry API that takes a user and tells you what
        # teams they're on as far as I can tell. Best we can do is get _all_ the
        # teams and _all_ their members and then do a reverse lookup.
        teams = self._get_paged_results(
            url=f"{self.baseurl}/api/0/organizations/mozilla/teams/",
            headers=headers,
        )
        members_to_teams = {}
        for team in teams:
            members = self._get_paged_results(
                url=f"{self.baseurl}/api/0/teams/mozilla/{team['slug']}/members/",
                headers=headers,
            )
            for member in members:
                key = member["email"].lower()
                members_to_teams.setdefault(key, []).append(team["name"])

        # Get all the users so we can match our offboard email against them
        users = self._get_paged_results(
            url=f"{self.baseurl}/api/0/organizations/mozilla/members/",
            headers=headers,
        )

        sentry_users = []
        for user in users:
            user_key = user["email"].lower()
            sentry_users.append(
                {
                    "account": user["email"],
                    "teams": members_to_teams.get(user_key, [])
                }
            )

        return sentry_users

    def get_matches(self, pattern):
        users = self.get_sentry_users()
        matched_users = []
        for user in users:
            if pattern in user["account"]:
                matched_users.append(user)
        return matched_users


class NewRelicData:
    def __init__(self, token):
        self.token = token

    def get_users(self):
        url = "https://api.newrelic.com/graphql"
        headers = {
            "Content-Type": "application/json",
            "API-Key": self.token,
        }
        # This (probably) gets all the accounts and account types
        query = '{ "query": "{ actor { organization { userManagement { authenticationDomains { authenticationDomains { users { users { id name email lastActive type { displayName id } } } } } } } } }" }'

        resp = requests.post(url, headers=headers, data=query)
        if "errors" in resp.json():
            click.echo(resp.status_code)
            click.echo(resp.json())
            raise Exception("New Relic API raised error")

        deeply_nested_user_data = resp.json()["data"]["actor"]["organization"]["userManagement"]["authenticationDomains"]["authenticationDomains"][0]["users"]["users"]

        users = []
        for user in deeply_nested_user_data:
            users.append(
                {
                    "account": user["email"],
                    "name": user["name"],
                    "type": user["type"]["displayName"],
                }
            )
        return users

    def get_matches(self, pattern):
        matched_users = []
        users = self.get_users()
        for user in users:
            if pattern in user["account"]:
                matched_users.append(user)
        return matched_users


class SolarWindsData:
    def __init__(self, users_file):
        self.users_file = users_file

    def get_users(self):
        with open(self.users_file, "r") as fp:
            data = fp.readlines()

        users = []
        for line in data:
            line = line.strip()
            if line.startswith("#"):
                continue
            # account, name, role, last_logged_in
            fields = line.split(",")
            users.append(
                {
                    "org": fields[0],
                    "account": fields[1],
                    "name": fields[2],
                    "role": fields[3],
                    "last_logged_in": fields[4],
                }
            )

        return users

    def get_matches(self, pattern):
        matched_users = []
        users = self.get_users()
        for user in users:
            if pattern in user["account"]:
                matched_users.append(user)
        return matched_users


class DeadMansSnitchData:
    def __init__(self, users_file):
        self.users_file = users_file

    def get_users(self):
        with open(self.users_file, "r") as fp:
            data = fp.readlines()

        users = []
        for line in data:
            line = line.strip()
            if line.startswith("#"):
                continue
            # account, name, role, last_logged_in
            fields = line.split(",")
            users.append(
                {
                    "case": fields[0],
                    "name": fields[1],
                    "account": fields[2],
                }
            )

        return users

    def get_matches(self, pattern):
        matched_users = []
        users = self.get_users()
        for user in users:
            if pattern in user["account"]:
                matched_users.append(user)
        return matched_users


@click.command()
@click.argument("email")
@click.pass_context
def main(ctx, email):
    click.echo(f"Offboarding {email}")
    click.echo("")

    # DeadMansSnitch
    deadmanssnitch_data = DeadMansSnitchData("deadmanssnitch_users.csv")
    matches = deadmanssnitch_data.get_matches(pattern=email)
    click.echo("DeadMansSnitch:")
    if matches:
        for user in matches:
            click.echo(f"  * {user['account']}: {user['case']}")
    else:
        click.echo("No account")
    click.echo("")

    ctx.exit(1)


    # Yardstick
    yardstick_data = GrafanaData(
        url="https://yardstick.mozilla.org",
        token=YARDSTICK_API_TOKEN,
    )
    yardstick_matches = yardstick_data.get_matches(pattern=email)
    click.echo("Yardstick:")
    if yardstick_matches:
        for user in yardstick_matches:
            click.echo(f"  * {user['account']}: {user['teams']}")
    else:
        click.echo("No account")
    click.echo("")

    # Sentry
    sentry_data = SentryData(url="https://sentry.io", token=SENTRY_API_TOKEN)
    sentry_matches = sentry_data.get_matches(pattern=email)
    click.echo("Sentry:")
    if sentry_matches:
        for user in sentry_matches:
            click.echo(f"  * {user['account']}: {user['teams']}")
    else:
        click.echo("No account")

    # New Relic
    newrelic_data = NewRelicData(token=NEWRELIC_API_TOKEN_CORPORATION_PRIMARY)
    newrelic_matches = newrelic_data.get_matches(pattern=email)
    click.echo("New Relic:")
    if newrelic_matches:
        for user in newrelic_matches:
            click.echo(f"  * {user['account']}: {user['type']}")
    else:
        click.echo("No account")

    # SolarWinds
    solarwinds_data = SolarWindsData("solarwinds_users.csv")
    matches = solarwinds_data.get_matches(pattern=email)
    click.echo("SolarWinds (pingdom / papertrail)")
    if matches:
        for user in matches:
            click.echo(f"  * {user['account']}: {user['org']}, {user['role']}")
    else:
        click.echo("No account")

    # TODO: DeadMansSnitch


if __name__ == "__main__":
    main()
