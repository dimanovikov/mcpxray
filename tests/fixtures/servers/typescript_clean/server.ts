// Clean TypeScript MCP server fixture — high-level @modelcontextprotocol/sdk API.
// Exercises both the registerTool form (config object + zod inputSchema) and the
// tool() shorthand (name, description, zod shape, handler). No secrets / no RCE.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

const server = new McpServer({ name: "clean-demo", version: "0.0.0" });

// registerTool: config object with explicit description + inputSchema (zod object).
server.registerTool(
  "greet",
  { description: "Greet a user by name.", inputSchema: z.object({ name: z.string() }) },
  async (args) => ({ content: [{ type: "text", text: `Hello, ${args.name}!` }] }),
);

// tool() shorthand: (name, description, zod shape, handler).
server.tool("add", "Add two numbers.", { a: z.number(), b: z.number() }, async (args) => ({
  content: [{ type: "text", text: String(args.a + args.b) }],
}));

// tool() shorthand with a z.array param.
server.tool("tags", "Count the tags.", { items: z.array(z.string()) }, async (args) => ({
  content: [{ type: "text", text: String(args.items.length) }],
}));

export { server };
