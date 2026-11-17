"""Company homepage: how the company describes itself (title + meta description).

Safety rules (this fetches a hostname that came from user/Wikidata data):
- https only, bare hostname only (no IP literals, ports, credentials, paths).
- The host is resolved first and refused unless EVERY address is public
  (private, loopback, link-local, reserved, multicast, CGNAT, NAT64/6to4 all blocked).
- We connect to the validated IP (no second DNS lookup), so DNS rebinding cannot swap it.
- Redirects: at most 3, same host (or its www/apex twin), https only, each hop re-validated.
- robots.txt is honored. 5s timeout, 1 MB cap, text/html only (from the shared client).
- Fetched text is passed through the guardrails sanitizer before it becomes a fact.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from ..guardrails import sanitize_web_text
from ..providers import SearchResult
from .http import HttpClient, HttpError

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
DNS_TIMEOUT = 3.0
MAX_QUOTED = 180
ROBOTS_TOKEN = "ColdCallConversion"
_HOST = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_6TO4 = ipaddress.ip_network("2002::/16")

Resolver = Callable[[str], list[str]]


class Refused(Exception):
    """The fetch was refused for safety or policy reasons (message is a note)."""


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


_GLOBAL_V6 = ipaddress.ip_network("2000::/3")


def is_public_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip in _NAT64 or ip in _6TO4 or ip.sixtofour or ip.teredo or ip not in _GLOBAL_V6:
            return False  # only global unicast 2000::/3 is allowed
    return ip.is_global and not ip.is_multicast


def normalize_domain(domain: str) -> str:
    """Bare lowercase hostname or Refused. Rejects URLs, ports, IP literals."""
    d = (domain or "").strip().lower().rstrip(".")
    if not _HOST.match(d):
        raise Refused("company domain is not a plain public hostname")
    return d


def _twin(a: str, b: str) -> bool:
    strip = lambda h: h[4:] if h.startswith("www.") else h
    return strip(a) == strip(b)


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title" and not self.title:
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 500:
            self.title += data


def parse_head(html: str) -> tuple[str, str]:
    """(title, description) from <title>, meta description or og:description."""
    p = _Head()
    try:
        p.feed(html)
    except Exception:
        pass
    desc = p.meta.get("og:description") or p.meta.get("description") or ""
    return p.title, desc


class HomepageSource:
    def __init__(self, http: HttpClient, resolver: Resolver = default_resolver, today: Optional[date] = None) -> None:
        self.http = http
        self.resolver = resolver
        self.today = today or date.today()
        self._robots: dict[str, Optional[RobotFileParser]] = {}

    # -- safe fetching ----------------------------------------------------
    def _safe_ip(self, host: str) -> str:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            addrs = pool.submit(self.resolver, host).result(timeout=DNS_TIMEOUT)
        except FutureTimeout:
            raise Refused("company domain lookup timed out")
        except Exception:
            raise Refused("company domain did not resolve")
        finally:
            pool.shutdown(wait=False)
        if not addrs or not all(is_public_ip(a) for a in addrs):
            raise Refused("company domain resolves to a non-public address; not fetched")
        return sorted(addrs, key=lambda a: ":" in a)[0]  # prefer IPv4

    def _get_once(self, url: str, content_types: Optional[tuple[str, ...]]):
        try:
            parts = urlsplit(url)
            bad = parts.scheme != "https" or parts.port not in (None, 443) or parts.username or parts.password
        except ValueError:
            bad = True
        if bad:
            raise Refused("only plain https URLs are fetched")
        host = parts.hostname or ""
        return self.http.get(url, max_bytes=MAX_BYTES, content_types=content_types, pin_ip=self._safe_ip(host))

    def _robots_for(self, host: str) -> Optional[RobotFileParser]:
        """Parsed robots.txt, or None meaning 'everything allowed'. Raises Refused if disallow-all."""
        if host in self._robots:
            return self._robots[host]
        rp: Optional[RobotFileParser] = None
        resp = self._get_once(f"https://{host}/robots.txt", ("text/plain", "text/html"))
        if resp.status >= 500 or 300 <= resp.status < 400:
            raise Refused("robots.txt unavailable or redirected; not fetched")
        if resp.status == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
        self._robots[host] = rp
        return rp

    def _fetch_page(self, url: str):
        """Fetch with robots checks and same-host redirects. Returns (final_url, response)."""
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            host = parts.hostname or ""
            rp = self._robots_for(host)
            if rp is not None and not rp.can_fetch(ROBOTS_TOKEN, url):
                raise Refused("robots.txt disallows fetching the company page")
            resp = self._get_once(url, ("text/html", "application/xhtml+xml"))
            if resp.status in (301, 302, 303, 307, 308):
                try:
                    nxt = urljoin(url, resp.headers.get("location", ""))
                    np = urlsplit(nxt)
                    np.port  # noqa: B018 - raises ValueError on a bogus port
                except ValueError:
                    raise Refused("redirect to an invalid URL refused")
                if np.scheme != "https":
                    raise Refused("redirect to a non-https URL refused")
                if not _twin(np.hostname or "", host):
                    raise Refused("redirect to a different host refused")
                url = nxt
                continue
            return url, resp
        raise Refused("too many redirects")

    # -- public -------------------------------------------------------------
    def describe(self, domain: str, unconfirmed_site: bool = False) -> tuple[list[SearchResult], list[str]]:
        """Return (results, notes). Never raises for expected failures.

        `unconfirmed_site` means the domain came from an exact-name-only match, so the
        fact says so. The quoted text is capped so the attribution is never truncated."""
        try:
            host = normalize_domain(domain)
            title, desc, final = self._read(f"https://{host}/")
            if not desc:  # at most one extra page
                _, desc2, final2 = self._read(f"https://{urlsplit(final).hostname}/about", quiet=True)
                title, desc, final = (title or "", desc2, final2) if desc2 else (title, desc, final)
        except Refused as exc:
            return [], [f"Company website not used: {exc}."]
        except HttpError as exc:
            return [], [f"Company website lookup failed ({exc})."]
        site = urlsplit(final).hostname or host
        title = sanitize_web_text(title, 150, redact=True)
        desc = sanitize_web_text(desc, 300, redact=True)
        if not desc:
            return [], ["Company website had no usable description."]
        if len(desc) > MAX_QUOTED:
            desc = desc[: MAX_QUOTED - 1].rsplit(" ", 1)[0].rstrip(" ,.;:") + "\u2026"
        who = "Website listed in Wikidata (unconfirmed match)" if unconfirmed_site else "Company website"
        text = f'{who} describes itself as: "{desc}" (self-description, not independently verified).'
        return [
            SearchResult(
                title=f"{site} homepage" + (f": {title}" if title else ""), url=final, publisher=site,
                published_date=self.today.isoformat(), content=desc,
                claims=[{"subject": "company", "key": "self_description",
                         "label": "How the company describes itself", "text": text, "value": desc}],
            )
        ], []

    def _read(self, url: str, quiet: bool = False) -> tuple[str, str, str]:
        try:
            final, resp = self._fetch_page(url)
        except (Refused, HttpError):
            if quiet:
                return "", "", url
            raise
        if resp.status != 200:
            if quiet:
                return "", "", final
            raise HttpError(f"HTTP {resp.status}")
        title, desc = parse_head(resp.text)
        return title, desc, final
