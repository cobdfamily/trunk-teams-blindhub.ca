# trunk-teams-blindhub.ca

[![test](https://github.com/cobdfamily/trunk-teams-blindhub.ca/actions/workflows/test.yml/badge.svg)](https://github.com/cobdfamily/trunk-teams-blindhub.ca/actions/workflows/test.yml)

Per-team production data for the **blindhub.ca** tenant of
[`cobdfamily/trunk`](https://github.com/cobdfamily/trunk).
Splits the blindhub menu + audio off
[`cobdfamily/trunk-teams-cobd.ca`](https://github.com/cobdfamily/trunk-teams-cobd.ca)
so blindhub edits don't churn the cobd.ca tree.

One repo == one team. Sibling repos hold each other team
(`cobdfamily/trunk-teams-cobd.ca`, more `trunk-teams-<name>`
as they come online).

The trunk deploy host clones this repo and bind-mounts its
root at `/app/data/teams/blindhub.ca` inside the trunk
container. The bind goes to the team-slot path, **not**
`/app/data` — a whole-data bind would shadow the trunk
image's built-in `/app/data/templates`.

```
audio/<file>                team-wide WAVs
                            (blindhub-greeting + mainmenu)
team.yaml                   signature_verification +
                            team_extensions_base_url
menus/languages.yaml        entry point. language selector
menus/mainmenu.en.yaml      English main menu (stub)
documents/<name>.xml.j2     (none yet)

tests/                      E2E harness (test_e2e.py)
docker-compose.yaml         brings up trunk with this repo
                            mounted at the blindhub.ca slot
```

## Cross-tenant routing

The blindhub language-selector menu's operator-dial options
(`0` -> ext 100, `3` -> ext 052) target the cobd.ca tenant
via absolute URLs back at
`phone.apps.blindhub.ca/v1/teams/cobd.ca/...`. blindhub.ca
has no PBX of its own; it shares cobd.ca's via cross-tenant
redirect. Extension lookups that miss locally fall through
to cobd.ca's tree automatically via `team.yaml`'s
`team_extensions_base_url`.

This works because both tenants run on the same trunk
instance (`phone.apps.blindhub.ca`), so a redirect from one
team to the other is just an HTTP 302 to a sibling path on
the same host. If a future deploy splits the tenants across
hosts, the absolute URLs would need updating.

## Bind-mount for production

In your trunk deploy host's compose:

```yaml
services:
  trunk:
    image: kibble.apps.blindhub.ca/cobdfamily/trunk:latest
    volumes:
      - /opt/trunk-teams-cobd.ca:/app/data/teams/cobd.ca:ro
      - /opt/trunk-teams-blindhub.ca:/app/data/teams/blindhub.ca:ro
      - ./config.yaml:/app/config.yaml:ro
```

Setup the host once:

```sh
sudo mkdir -p /opt
sudo git clone https://github.com/cobdfamily/trunk-teams-blindhub.ca \
     /opt/trunk-teams-blindhub.ca
```

Update later:

```sh
cd /opt/trunk-teams-blindhub.ca && git pull
```

No container restart needed.

## Schema

The canonical reference for every YAML field here lives in
the trunk repo at
[`SCHEMA.md`](https://github.com/cobdfamily/trunk/blob/main/SCHEMA.md).

## End-to-end tests

`docker-compose.yaml` brings up `cobdfamily/trunk` with this
checkout mounted at `/app/data/teams/blindhub.ca`. The
`tests/test_e2e.py` smoke-test walks the menu path and
asserts the rendered TwiML.

```sh
docker compose up -d

python3 -m venv tests/.venv
tests/.venv/bin/pip install -r tests/requirements.txt
tests/.venv/bin/python -m pytest tests/test_e2e.py -v

docker compose down -v
```

## CI

`.github/workflows/test.yml` runs the E2E suite on push, on
PR, and nightly at 07:15 UTC (offset from cobd.ca's 07:00
nightly so they don't compete for kibble pulls).

## License

AGPL-3.0 — see `LICENSE`.
