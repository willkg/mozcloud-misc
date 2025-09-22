# README

This is a set of MozCloud scripts that I threw together to do various things.

Note: This isn't production-quality. Some of these are used rarely so they may not work anymore.


## offboard_user.py

To run:

```shell
uv run offboard_user.py [EMAIL]
```

`EMAIL` can be a full email address or a partial email address. For example, I get tired typing my name, so I could type:

```shell
uv run offboard_user.py kahn
```

It'll pull up all the accounts with "kahn" in the account name / email address.

It prints out all the services it checked and whether there were accounts and properties of the account.

### Maintenance

The `data/solarwinds_users.csv` file is built manually by copying and pasting from the ui. It stinks. We don't have to do it often because we don't create new accounts very often (if ever).

The `data/deadmanssnitch_users.csv` file is also built manually by copying and pasting from the ui. It's not bad--takes about 10 minutes. We don't often add new accounts, so this is largely static.

## Yardstick/Grafana scripts

### grafana_stats

```shell
uv run grafana_stats.py 
```

Generates some stats about what we have in Grafana:

* list of dashboards and folders
* notification channels
* alert rules


### grafana_user_dashboards.py

```shell
uv run grafana_user_dashboards.py [USER]
```

Lists dashboards created or edited by the specified user.


### grafana_user_list_fix.py

```shell
uv run grafana_user_list_fix.py
```

Takes a `user_list.tsv` file downloaded from Grafana, fixes it, and displays the output.
