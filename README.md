# README

To run:

```
uv run offboard_user.py [EMAIL]
```

EMAIL can be a full email address or a partial email address. For example, I
get tired typing my name, so I could type:

```
uv run offboard_user.py kahn
```

And it'll pull up all the accounts with "kahn" in the account name / email
address.

It prints out all the services it checked and whether there were accounts and
properties of the account.


## Maintenance

The `solarwinds_users.csv` file is built manually by copying and pasting from
the ui. It sucks. We don't have to do it often because we don't create new
accounts very often (if ever).

The `deadmanssnitch_users.csv` file is also built manually by copying and
pasting from the ui. It's not bad--takes about 10 minutes. We don't often add
new accounts, so this is largely static.
