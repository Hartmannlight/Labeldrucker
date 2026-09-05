from __future__ import annotations

import pytest

from printer_fleet.auth import BearerCredentialAuthenticator, FleetPrincipal


def test_structured_credentials_create_scoped_principals(monkeypatch) -> None:
    monkeypatch.delenv("PRINTER_FLEET_API_TOKEN", raising=False)
    monkeypatch.setenv(
        "PRINTER_FLEET_CREDENTIALS_JSON",
        """{
          "credentials": [{
            "id": "printhub-berlin",
            "token": "0123456789abcdef",
            "roles": ["submitter", "observer"],
            "sites": ["berlin"]
          }]
        }""",
    )
    authenticator = BearerCredentialAuthenticator.from_environment()

    principal = authenticator.authenticate("Bearer 0123456789abcdef")

    assert principal == FleetPrincipal(
        id="printhub-berlin",
        roles=frozenset({"submitter", "observer"}),
        sites=frozenset({"berlin"}),
    )
    assert authenticator.authenticate("Bearer wrong") is None


def test_removed_global_token_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("PRINTER_FLEET_API_TOKEN", "legacy")

    with pytest.raises(ValueError, match="was removed"):
        BearerCredentialAuthenticator.from_environment()


@pytest.mark.parametrize(
    "document",
    [
        '{"credentials": [{"id":"a","token":"short","roles":["admin"],"sites":["*"]}]}',
        '{"credentials": [{"id":"a","token":"0123456789abcdef","roles":["root"],"sites":["*"]}]}',
        '{"credentials": [{"id":"a","token":"0123456789abcdef","roles":["admin"],"sites":["*","berlin"]}]}',
    ],
)
def test_invalid_structured_credentials_fail_startup(monkeypatch, document) -> None:
    monkeypatch.delenv("PRINTER_FLEET_API_TOKEN", raising=False)
    monkeypatch.setenv("PRINTER_FLEET_CREDENTIALS_JSON", document)

    with pytest.raises(ValueError):
        BearerCredentialAuthenticator.from_environment()
