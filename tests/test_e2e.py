"""End-to-end tests for the trunk-teams-blindhub.ca tree.

Assumes the docker-compose stack at the repo root is up --
trunk serving from this checkout (bind-mounted at
/app/data/teams/blindhub.ca).

The tests walk the menu render Twilio hits and verify the
rendered TwiML. blindhub.ca's mainmenu has only one
"internal" path (`/documents/bh-en-coming-soon` -- currently
404s because the document hasn't been authored yet) plus
cross-tenant redirects to cobd.ca for the operator-dial
options. We assert the menu shape; the cross-tenant
resolution is covered in cobdfamily/trunk-teams-cobd.ca's
test suite.
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


def test_mainmenu_renders_with_prompt():
    """Fresh menu hit (no Digits) emits a Gather with the
    prompt audio inside. Pins the audio path resolves under
    the blindhub.ca base_url (not cobd.ca's)."""
    r = _post("/v1/teams/blindhub.ca/menus/mainmenu")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    body = r.text
    assert "<Gather " in body
    assert "/v1/teams/blindhub.ca/audio/greeting.wav" in body
    # No accidental cobd.ca audio path leaked through.
    assert "/v1/teams/cobd.ca/audio/" not in body


def test_mainmenu_cross_tenant_redirect_on_operator_digit():
    """Pressing 0 routes to cobd.ca's ext 100 via an absolute
    URL. The <Redirect> body should be the literal cobd.ca
    URL -- trunk doesn't rewrite absolute URLs."""
    r = _post("/v1/teams/blindhub.ca/menus/mainmenu", Digits="0")
    assert r.status_code == 200
    body = r.text
    assert "<Redirect" in body
    assert (
        "https://phone.apps.blindhub.ca/v1/teams/cobd.ca/extensions/100"
        in body
    )


def test_mainmenu_invalid_digit_replays():
    """Garbage DTMF emits invalid-selection + re-gathers
    against the team's audio dir, not cobd.ca's."""
    r = _post("/v1/teams/blindhub.ca/menus/mainmenu", Digits="999")
    body = r.text
    assert "<Redirect" not in body
    assert (
        "/v1/teams/blindhub.ca/audio/invalid-selection.wav" in body
    )
    assert "<Gather " in body


def test_audio_served_under_team_slot():
    """The team's audio dir is reachable; pin one of the two
    WAVs the deploy depends on. Audio is binary; we don't
    parse it, just verify a 200 + non-empty body."""
    r = requests.get(
        TRUNK_BASE_URL + "/v1/teams/blindhub.ca/audio/greeting.wav",
        headers=PROXY_HEADERS,
        timeout=10,
    )
    assert r.status_code == 200
    assert len(r.content) > 1000
