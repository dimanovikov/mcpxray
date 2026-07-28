// Schema/implementation-drift fixture (MCP105) — declared schema disagrees with
// the handler's destructured parameters.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

const server = new McpServer({ name: "drift-demo", version: "0.0.0" });

// Schema declares {a, b}; the handler destructures {a, c} → drift both ways:
//   b: schema declares it, the handler never reads it
//   c: the handler reads it, the schema doesn't validate it
server.tool("mismatch", "Schema and handler disagree.", { a: z.string(), b: z.string() }, async ({ a, c }) => ({
  content: [{ type: "text", text: String(a) + String(c) }],
}));

// Consistent: schema {x}, handler reads {x} → no drift.
server.tool("consistent", "Schema and handler agree.", { x: z.number() }, async ({ x }) => ({
  content: [{ type: "text", text: String(x) }],
}));

export { server };
