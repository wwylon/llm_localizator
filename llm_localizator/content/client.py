"""HTTP client for a project's content API. Any host; the review UI is not one."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .contract import ContentUnit, ContractError, parse_page

__all__ = [
    "TOKEN_ENV",
    "URL_ENV",
    "ContentAPIError",
    "ContentClient",
    "endpoint_from_env",
]

URL_ENV = "LLM_LOCALIZE_CONTENT_URL"
TOKEN_ENV = "LLM_LOCALIZE_CONTENT_TOKEN"
_PAGE_LIMIT = 100
_MAX_PAGES = 50


class ContentAPIError(RuntimeError):
    """The content API could not be read or written. Not a catalogue error."""


def endpoint_from_env() -> tuple[str, str]:
    url = os.environ.get(URL_ENV, "").strip()
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not url:
        raise ContentAPIError(f"{URL_ENV} is not set")
    if not token:
        raise ContentAPIError(f"{TOKEN_ENV} is not set")
    return url, token


class ContentClient:
    """Calls ``GET/PUT {base}/v1/units``. ``base`` is whatever URL the env names."""

    def __init__(self, base_url: str, token: str, *, opener=None, timeout: float = 30) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.token = token
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def list_units(self) -> list[ContentUnit]:
        units: list[ContentUnit] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            payload = self._json("GET", self._list_url(cursor))
            try:
                page, cursor = parse_page(payload)
            except ContractError as exc:
                raise ContentAPIError(str(exc)) from exc
            units.extend(page)
            if not cursor:
                return units
            if cursor in seen:
                raise ContentAPIError("content API repeated next_cursor")
            seen.add(cursor)
        raise ContentAPIError("content API pagination did not end")

    def put_translation(self, unit_id: str, locale: str, body: dict) -> None:
        url = self._units_root() + "/" + _quote_id(unit_id) + "/" + urllib.parse.quote(locale, safe="")
        self._json("PUT", url, body)

    def _list_url(self, cursor: str | None) -> str:
        query = {"limit": str(_PAGE_LIMIT)}
        if cursor:
            query["cursor"] = cursor
        return self._units_root() + "?" + urllib.parse.urlencode(query)

    def _units_root(self) -> str:
        if self.base_url.endswith("/v1/units"):
            return self.base_url
        return self.base_url + "/v1/units"

    def _json(self, method: str, url: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            resp = self._opener(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ContentAPIError(f"HTTP {exc.code} for {method} {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ContentAPIError(f"content API unreachable ({url}): {exc.reason}") from exc
        with resp:
            raw = resp.read()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ContentAPIError(f"content API returned non-JSON for {method} {url}") from exc
        if not isinstance(parsed, dict):
            raise ContentAPIError(f"content API returned a non-object for {method} {url}")
        return parsed


def _quote_id(unit_id: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in unit_id.split("/"))
