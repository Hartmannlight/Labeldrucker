from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
from typing import Any, Protocol


_ROLES = {"admin", "observer", "submitter"}


@dataclass(frozen=True)
class FleetPrincipal:
    id: str
    roles: frozenset[str]
    sites: frozenset[str]

    def has_any_role(self, *roles: str) -> bool:
        return "admin" in self.roles or bool(self.roles.intersection(roles))

    def allows_site(self, site_id: str) -> bool:
        return "*" in self.sites or site_id in self.sites

    @property
    def is_global_admin(self) -> bool:
        return "admin" in self.roles and "*" in self.sites


class FleetAuthenticator(Protocol):
    @property
    def enabled(self) -> bool: ...

    def authenticate(self, authorization: str) -> FleetPrincipal | None: ...


class BearerCredentialAuthenticator:
    def __init__(self, credentials: list[tuple[str, FleetPrincipal]]) -> None:
        self._credentials = credentials

    @property
    def enabled(self) -> bool:
        return bool(self._credentials)

    def authenticate(self, authorization: str) -> FleetPrincipal | None:
        if not self.enabled:
            return FleetPrincipal(
                id="development",
                roles=frozenset({"admin"}),
                sites=frozenset({"*"}),
            )
        supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        matched: FleetPrincipal | None = None
        for token, principal in self._credentials:
            if secrets.compare_digest(supplied, token):
                matched = principal
        return matched

    @classmethod
    def from_environment(cls) -> BearerCredentialAuthenticator:
        inline = os.getenv("PRINTER_FLEET_CREDENTIALS_JSON", "").strip()
        path = os.getenv("PRINTER_FLEET_CREDENTIALS_FILE", "").strip()
        legacy_token = os.getenv("PRINTER_FLEET_API_TOKEN", "").strip()
        if legacy_token:
            raise ValueError(
                "PRINTER_FLEET_API_TOKEN was removed; configure structured Fleet credentials"
            )
        if inline and path:
            raise ValueError("Configure only one Fleet credentials source")
        if inline or path:
            raw = inline if inline else Path(path).read_text(encoding="utf-8")
            return cls(_parse_credentials(json.loads(raw)))
        return cls([])


def _parse_credentials(document: Any) -> list[tuple[str, FleetPrincipal]]:
    if not isinstance(document, dict) or not isinstance(document.get("credentials"), list):
        raise ValueError("Fleet credentials require a credentials list")
    parsed: list[tuple[str, FleetPrincipal]] = []
    ids: set[str] = set()
    tokens: set[str] = set()
    for item in document["credentials"]:
        if not isinstance(item, dict):
            raise ValueError("Every Fleet credential must be an object")
        principal_id = str(item.get("id") or "").strip()
        token = str(item.get("token") or "")
        roles_value = item.get("roles")
        sites_value = item.get("sites")
        if not principal_id or principal_id in ids:
            raise ValueError("Fleet credential ids must be present and unique")
        if len(token) < 16 or token in tokens:
            raise ValueError("Fleet credential tokens must be unique and at least 16 characters")
        if not isinstance(roles_value, list) or not roles_value:
            raise ValueError("Fleet credential roles must be a non-empty list")
        roles = frozenset(str(role) for role in roles_value)
        if not roles <= _ROLES:
            raise ValueError("Fleet credential contains an unsupported role")
        if not isinstance(sites_value, list) or not sites_value:
            raise ValueError("Fleet credential sites must be a non-empty list")
        sites = frozenset(str(site).strip() for site in sites_value)
        if "" in sites or ("*" in sites and len(sites) != 1):
            raise ValueError("Fleet credential sites must be explicit or the single wildcard")
        ids.add(principal_id)
        tokens.add(token)
        parsed.append((token, FleetPrincipal(principal_id, roles, sites)))
    return parsed
