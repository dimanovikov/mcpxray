"""Schema rules: weak/unvalidatable schemas (MCP104) and strict-client compatibility (MCP106)."""

from __future__ import annotations

from mcpscore.ir import RISK_MEDIUM, SEVERITY_WARNING, Diagnostic, McpServer
from mcpscore.rules.base import Rule, register_rule

# Keywords strict clients (Cursor, ChatGPT tool-calling) handle poorly or reject.
_STRICT_INCOMPAT_KEYS = ("$ref", "oneOf", "anyOf", "allOf")


@register_rule
class WeakSchema(Rule):
    id = "MCP104"
    severity = SEVERITY_WARNING
    risk = RISK_MEDIUM

    def check(self, doc: McpServer):  # type: ignore[override]
        for tool in doc.tools:
            schema = tool.input_schema or {}
            props = schema.get("properties") or {}
            required = schema.get("required") or []
            if props and not required:
                yield Diagnostic(
                    self.id,
                    self.severity,
                    f"tool '{tool.name}': schema has no required parameters -- accepts anything",
                    tool=tool.name,
                    file=tool.source_path,
                    line=tool.line,
                )
            for pname, pschema in props.items():
                if isinstance(pschema, dict) and not pschema:
                    yield Diagnostic(
                        self.id,
                        self.severity,
                        f"tool '{tool.name}': parameter '{pname}' has no type -- unvalidatable",
                        tool=tool.name,
                        file=tool.source_path,
                        line=tool.line,
                    )


@register_rule
class SchemaCompatibility(Rule):
    id = "MCP106"
    severity = SEVERITY_WARNING
    risk = RISK_MEDIUM

    def check(self, doc: McpServer):  # type: ignore[override]
        for tool in doc.tools:
            schema = tool.input_schema or {}
            if not isinstance(schema, dict) or not schema:
                continue
            bad = next((k for k in _STRICT_INCOMPAT_KEYS if k in schema), None)
            if bad:
                yield Diagnostic(
                    self.id,
                    self.severity,
                    f"tool '{tool.name}': schema uses '{bad}', which strict clients "
                    f"(Cursor/ChatGPT) may reject",
                    tool=tool.name,
                    file=tool.source_path,
                    line=tool.line,
                )
            elif "type" not in schema and "properties" not in schema:
                yield Diagnostic(
                    self.id,
                    self.severity,
                    f"tool '{tool.name}': schema declares no 'type'",
                    tool=tool.name,
                    file=tool.source_path,
                    line=tool.line,
                )


@register_rule
class SchemaImplDrift(Rule):
    """MCP105 — a tool's declared inputSchema disagrees with its handler.

    Caught when the handler destructures its arguments (so we know what it reads):
    a parameter the schema declares but the handler ignores (clients must send
    data the tool never uses), or one the handler reads but the schema doesn't
    declare (unvalidated input bypasses the schema). Skipped when
    :attr:`Tool.handler_params` is ``None`` — i.e. a bare ``args`` handler,
    Python (where the schema *is* the signature), or a manifest tool.
    """

    id = "MCP105"
    severity = SEVERITY_WARNING
    risk = RISK_MEDIUM

    def check(self, doc: McpServer):  # type: ignore[override]
        for tool in doc.tools:
            if tool.handler_params is None:
                continue  # can't compare — undeterminable handler signature
            declared = set((tool.input_schema or {}).get("properties") or {})
            used = set(tool.handler_params)
            ignored = sorted(declared - used)  # schema declares, handler doesn't read
            unvalidated = sorted(used - declared)  # handler reads, schema doesn't validate
            if not (ignored or unvalidated):
                continue
            parts: list[str] = []
            if ignored:
                parts.append(f"schema declares {ignored} but the handler doesn't read them")
            if unvalidated:
                parts.append(f"handler reads {unvalidated} but the schema doesn't declare them")
            yield Diagnostic(
                self.id,
                self.severity,
                f"tool '{tool.name}': " + "; ".join(parts),
                tool=tool.name,
                file=tool.source_path,
                line=tool.line,
            )
