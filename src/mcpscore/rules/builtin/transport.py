"""Transport rule: insecure network transport without TLS / auth (MCP109)."""

from __future__ import annotations

import re

from mcpscore.ir import RISK_MEDIUM, SEVERITY_WARNING, Diagnostic, McpServer
from mcpscore.rules.base import Rule, register_rule

# Construction of an HTTP/SSE-based MCP transport (stdio is local and safe).
# Covers the TS SDK (StreamableHTTP/SSE transports, ``transport: "http"|"sse"``)
# and Python FastMCP (``.run(transport="http"|"sse"|"streamable_http")``).
_HTTP_TRANSPORT_RE = re.compile(
    r"StreamableHTTPServerTransport"
    r"|SSEServerTransport"
    r"|transport\s*[:=]\s*['\"](?:streamable_http|http|sse)['\"]"
    r"|\.(?:connect|serve|start)\s*\(\s*['\"](?:http|sse)['\"]",
    re.IGNORECASE,
)

# A non-loopback plain-HTTP endpoint — transport without TLS.
_INSECURE_URL_RE = re.compile(r"http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?)")

# Signals that transport is encrypted or authenticated (suppress MCP109).
_TLS_RE = re.compile(
    r"https://|\bssl\b|\btls\b|createSecureContext|SecureServer|SSLContext",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(
    r"authenticate|authorization|bearer|api[_-]?key|authmiddleware|verifytoken"
    r"|requires_auth|httpbasic|oauth|verify_token|@authenticated",
    re.IGNORECASE,
)


@register_rule
class InsecureTransport(Rule):
    """MCP109 — an HTTP/SSE transport exposed without TLS or authentication.

    Only inspected when the server actually constructs a network transport
    (``stdio`` is local, so it's out of scope). Two independent warnings:

    * a non-loopback ``http://`` endpoint and no TLS anywhere → *no encryption*;
    * no auth primitive anywhere → *unauthenticated* (any reachable client can
      invoke the tools).

    Both are warnings: a reverse proxy may legitimately provide TLS/auth, so the
    finding is surfaced for review rather than treated as a hard error.
    """

    id = "MCP109"
    severity = SEVERITY_WARNING
    risk = RISK_MEDIUM

    def applies(self, doc: McpServer) -> bool:
        return bool(doc.sources)

    def check(self, doc: McpServer):  # type: ignore[override]
        blob = "\n".join(doc.sources.values())
        if not _HTTP_TRANSPORT_RE.search(blob):
            return  # stdio / no transport — nothing to flag
        has_tls = bool(_TLS_RE.search(blob))
        has_auth = bool(_AUTH_RE.search(blob))
        if _INSECURE_URL_RE.search(blob) and not has_tls:
            yield Diagnostic(
                self.id,
                self.severity,
                "HTTP transport endpoint without TLS — use https so tool traffic "
                "isn't sent in the clear",
                file=doc.meta.path,
            )
        if not has_auth:
            yield Diagnostic(
                self.id,
                self.severity,
                "network transport exposed without authentication — any reachable "
                "client can invoke these tools",
                file=doc.meta.path,
            )
