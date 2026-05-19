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


def test_languages_press_0_redirects_to_operator_extension():
    """Pressing 0 emits a Redirect to this team's
    /extensions/100. The actual cross-team hop to cobd.ca's
    PBX is handled at the extension route via
    ``team_extensions_base_url`` -- blindhub has no local
    profile for 100, so blindhub.ca/extensions/100 302s
    over to cobd.ca/extensions/100 on the second hop.
    That second hop is trunk's own responsibility and is
    covered in cobdfamily/trunk's e2e suite; here we just
    pin the menu's emit."""
    r = _post("/v1/teams/blindhub.ca/menus/languages", Digits="0")
    assert r.status_code == 200
    body = r.text
    assert "<Redirect" in body
    assert (
        "https://phone.example/v1/teams/blindhub.ca/extensions/100"
        in body
    )


def test_languages_press_1_2_3_routes_to_language_mainmenus():
    """The language selector dispatches 1/2/3 to the
    English / French / Spanish main-menus respectively.
    Pin so a refactor that swaps the mapping doesn't sneak
    out a French caller dialed into the English ext."""
    cases = [
        ("1", "mainmenu.en"),
        ("2", "mainmenu.fr"),
        ("3", "mainmenu.es"),
    ]
    for digit, target in cases:
        r = _post("/v1/teams/blindhub.ca/menus/languages", Digits=digit)
        body = r.text
        assert (
            f"https://phone.example/v1/teams/blindhub.ca/menus/{target}"
            in body
        ), f"Digits={digit!r} did not route to {target}"


def test_language_mainmenu_renders_tts_prompt_with_brian_voice():
    """Each language mainmenu uses ``prompt_text`` (TTS via
    talkshow) and inherits the team's Brian Multilingual
    voice param. Hit one of them and assert the resulting
    Play URL points at talkshow's /v1/speak with
    voice=...&text=... wired up."""
    r = _post("/v1/teams/blindhub.ca/menus/mainmenu.en")
    body = r.text
    # Talkshow base URL comes from team.yaml.
    assert "newsline.apps.blindhub.ca/v1/speak?" in body, body
    # Brian Multilingual is the team-default voice.
    assert "voice=en-US-BrianMultilingualNeural" in body, body
    # text= must reflect the English prompt.
    assert "BlindHub" in body  # word in URL-encoded form


def test_language_mainmenu_press_0_routes_to_language_extension():
    """English / French / Spanish mainmenus each press-0 to
    the operator extension for that language. Pin the
    mapping so a future menu edit doesn't accidentally
    cross-route (e.g. French caller -> Spanish operator)."""
    cases = [
        ("mainmenu.en", "100"),
        ("mainmenu.fr", "033"),
        ("mainmenu.es", "052"),
    ]
    for menu, ext in cases:
        r = _post(f"/v1/teams/blindhub.ca/menus/{menu}", Digits="0")
        body = r.text
        assert (
            f"https://phone.example/v1/teams/blindhub.ca/extensions/{ext}"
            in body
        ), f"{menu} press-0 didn't route to ext {ext}"


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
