"""End-to-end tests for the trunk-teams-blindhub.ca tree.

Assumes the docker-compose stack at the repo root is up --
trunk serving from this checkout (bind-mounted at
/app/data/teams/blindhub.ca).

The tests walk the menu render Twilio hits and verify the
rendered TwiML. blindhub.ca's entry-point menu is
``/menus/languages`` (since the mainmenu.yaml split into a
language-selector + English main menu in May 2026). Options
mostly cross-tenant-redirect to cobd.ca for the operator-
dial flows; we assert the menu shape here, cross-tenant
resolution is covered in trunk-teams-cobd.ca's test suite.
"""

from __future__ import annotations

import os

import requests


TRUNK_BASE_URL = os.environ.get("TRUNK_BASE_URL", "http://localhost:1962")

# X-Forwarded-* headers the tests send so trunk emits URLs
# that match this hardcoded host (rather than http://trunk:
# 1962, which Twilio would never reach in production).
# Mirrors what the reverse proxy does in front of trunk on
# the deploy host.
PROXY_HEADERS = {
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Host": "phone.example",
}


def _post(path: str, **form) -> requests.Response:
    """POST a Twilio-shaped form-urlencoded webhook to trunk.
    ``allow_redirects=False`` so a 302 doesn't DNS-resolve
    against the test public host."""
    return requests.post(
        TRUNK_BASE_URL + path,
        data=form,
        headers=PROXY_HEADERS,
        timeout=10,
        allow_redirects=False,
    )


def test_trunk_liveness():
    r = requests.get(TRUNK_BASE_URL + "/", timeout=5)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service"] == "trunk"
    assert body["status"] == "ok"
    assert body["version"]


def test_languages_renders_with_prompt():
    """Fresh hit on the entry-point menu (no Digits) emits a
    Gather with the prompt audio inside. Pins the audio
    path resolves under the blindhub.ca base_url (not
    cobd.ca's)."""
    r = _post("/v1/teams/blindhub.ca/menus/languages")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    body = r.text
    assert "<Gather " in body
    assert "/v1/teams/blindhub.ca/audio/blindhub-greeting.wav" in body
    # No accidental cobd.ca audio path leaked through.
    assert "/v1/teams/cobd.ca/audio/" not in body


def test_languages_cross_tenant_redirect_on_operator_digit():
    """Pressing 0 routes to cobd.ca's ext 100 via an absolute
    URL. The <Redirect> body should be the literal cobd.ca
    URL -- trunk doesn't rewrite absolute URLs."""
    r = _post("/v1/teams/blindhub.ca/menus/languages", Digits="0")
    assert r.status_code == 200
    body = r.text
    assert "<Redirect" in body
    assert (
        "https://phone.apps.blindhub.ca/v1/teams/cobd.ca/extensions/100"
        in body
    )


def test_languages_invalid_digit_replays():
    """Garbage DTMF emits invalid-selection + re-gathers
    against the team's audio dir, not cobd.ca's.

    Uses a 2-digit press to stay below trunk's 3-/4-digit
    dial-through regex -- with team_extensions_base_url
    pointing at cobd.ca, a 3-digit press would dial-through
    instead of falling to invalid-selection. v5.7.23 also
    adds a trailing silent-loop <Redirect> on every menu
    render; the test allows for that but pins the absence
    of a dispatch redirect to any /extensions/<n> target."""
    r = _post("/v1/teams/blindhub.ca/menus/languages", Digits="99")
    body = r.text
    assert "<Gather " in body
    assert (
        "/v1/teams/blindhub.ca/audio/invalid-selection.wav" in body
    )
    # No dispatch redirect -- the only <Redirect> is the
    # silent-loop self-loop with ?attempt=1.
    assert "/extensions/" not in body
    assert "?attempt=1</Redirect>" in body


def test_audio_served_under_team_slot():
    """The team's audio dir is reachable; pin one of the two
    WAVs the deploy depends on. Audio is binary; we don't
    parse it, just verify a 200 + non-empty body."""
    r = requests.get(
        TRUNK_BASE_URL + "/v1/teams/blindhub.ca/audio/blindhub-greeting.wav",
        headers=PROXY_HEADERS,
        timeout=10,
    )
    assert r.status_code == 200
    assert len(r.content) > 1000
