// Low-level TypeScript MCP server fixture — setRequestHandler(ListToolsRequestSchema, …).
// Tools are returned as a literal array; inputSchema is a real JSON-Schema object.
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  { name: "lowlevel-demo", version: "0.0.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "ping",
      description: "Health-check ping.",
      inputSchema: {
        type: "object",
        properties: { host: { type: "string" } },
        required: ["host"],
      },
    },
  ],
}));

export { server };
