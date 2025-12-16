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

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Goes through and lists which accounts that person owns across observability
services.
"""

import os

import click
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
import requests


load_dotenv()


YARDSTICK_API_TOKEN = os.getenv("YARDSTICK_API_TOKEN")
YARDSTICK_IAP_TOKEN = os.getenv("YARDSTICK_IAP_TOKEN")

SENTRY_API_TOKEN = os.getenv("SENTRY_API_TOKEN")

NEWRELIC_API_TOKEN_CORPORATION_PRIMARY = os.getenv(
    "NEWRELIC_API_TOKEN_CORPORATION_PRIMARY"
)


class GrafanaData:
    def __init__(self, url, token, iap_token):
        self.url = url
        self.token = token
        self.iap_token = iap_token
        self._users = []

    def _get(self, url, path):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Proxy-Authorization": f"Bearer {self.iap_token}",
            "Content-Type": "application/json",
        }
        resp = requests.get(f"{url}{path}", headers=headers)
        resp.raise_for_status()
        return resp.json()

    def _get_teams_for_user(self, user_id):
        # FIXME(willkg): can't do this with a service account token--it
        # requires users:read which service account tokens don't have. there
        # doesn't seem to be a way to get the list of teams a user belongs to
        # with a service account token.
        teams = self._get(self.url, f"/api/users/{user_id}/teams")
        return [team["name"] for team in teams]

    def _get_users(self):
        if not self._users:
            self._users = self._get(self.url, "/api/org/users")

        return self._users

    def get_matches(self, pattern):
        users = self._get_users()
        matched_users = []
        for user in users:
            if pattern in user["email"].lower():
                # FIXME(willkg): "teams": self._get_teams_for_user(user["userId"]),
                matched_users.append(f"{user['email']}: unknown teams")

        return matched_users


class SentryData:
    def __init__(self, url, token):
        self.baseurl = url
        self.token = token
        self._users = []

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

    def _get_users(self):
        """Get email addresses and teams for all active sentry users."""
        if not self._users:
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
                        "teams": members_to_teams.get(user_key, []),
                    }
                )
            self._users = sentry_users

        return self._users

    def get_matches(self, pattern):
        users = self._get_users()
        matched_users = []
        for user in users:
            if pattern in user["account"]:
                matched_users.append(f"{user['account']}: {user['teams']}")
        return matched_users


class NewRelicData:
    def __init__(self, token):
        self.token = token
        self._users = []

    def _get_users(self):
        if not self._users:
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

            deeply_nested_user_data = resp.json()["data"]["actor"]["organization"][
                "userManagement"
            ]["authenticationDomains"]["authenticationDomains"][0]["users"]["users"]

            users = []
            for user in deeply_nested_user_data:
                users.append(
                    {
                        "account": user["email"],
                        "name": user["name"],
                        "type": user["type"]["displayName"],
                    }
                )
            self._users = users
        return self._users

    def get_matches(self, pattern):
        matched_users = []
        users = self._get_users()
        for user in users:
            if pattern in user["account"]:
                matched_users.append(f"{user['account']}: {user['type']}")
        return matched_users


class SolarWindsData:
    def __init__(self, users_file):
        self.users_file = users_file
        self._users = []

    def _get_users(self):
        if not self._users:
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
            self._users = users

        return self._users

    def get_matches(self, pattern):
        users = self._get_users()
        matched_users = []
        for user in users:
            if pattern in user["account"]:
                matched_users.append(
                    f"{user['account']}: {user['org']}, {user['role']}"
                )
        return matched_users


@click.command()
@click.pass_context
def main(ctx):
    """
    Goes through and lists which accounts that person owns across observability
    services.

    Create API tokens and set these in the `.env` file:

    \b
    * YARDSTICK_API_TOKEN
    * SENTRY_API_TOKEN
    * NEWRELIC_API_TOKEN_CORPORATE_PRIMARY

    Before running this, you have to get the Yardstick IAP token:

    \b
    export YARDSTICK_IAP_TOKEN=$(gcloud auth print-identity-token \
            --impersonate-service-account SERVICEACCOUNT \
            --audiences CLIENTID --include-email)

    Where:

    \b
    * SERVICEACCOUNT: the service account tied to Yardstick Prod IAP
    * CLIENTID: the client id for Yardstick Prod IAP

    IAP tokens expire after some time, so you have to re-up the token
    periodically.

    """

    providers = {
        "Yardstick": GrafanaData(
            url="https://yardstick.mozilla.org",
            token=YARDSTICK_API_TOKEN,
            iap_token=YARDSTICK_IAP_TOKEN,
        ),
        "Sentry": SentryData(url="https://sentry.io", token=SENTRY_API_TOKEN),
        "NewRelic": NewRelicData(token=NEWRELIC_API_TOKEN_CORPORATION_PRIMARY),
        "SolarWinds": SolarWindsData("data_offboard/solarwinds_users.csv"),
    }

    prompt_session = PromptSession()

    while True:
        to_offboard = prompt_session.prompt("Person to offboard: ")
        offboard = to_offboard.split(" ")

        for item in offboard:
            item = item.strip()
            if not item:
                continue

            click.echo(f"Offboarding {item}")
            patterns = [item]
            if "@" in item:
                patterns.append(item.split("@")[0])

            # Provider -> list of accounts
            provider_to_matches = {provider: set() for provider in providers.keys()}

            for pattern in patterns:
                for key, provider in providers.items():
                    for match in provider.get_matches(pattern):
                        provider_to_matches[key].add(match)

            for provider, matches in provider_to_matches.items():
                if not matches:
                    click.echo(f"{provider}: no accounts")
                else:
                    click.echo(provider)
                    for match in matches:
                        click.echo(f"  * {match}")

            click.echo("")


if __name__ == "__main__":
    main()
