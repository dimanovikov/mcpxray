// Leaky TypeScript MCP server fixture — a hardcoded API key (MCP102 → error).
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

// Hardcoded secret — must be flagged by MCP102 (sk- + 20+ alphanumerics).
const OPENAI_API_KEY = "sk-1234567890abcdef1234567890abcdef";

const server = new McpServer({ name: "leaky-demo", version: "0.0.0" });

server.tool("echo", "Echo a message back.", { msg: z.string() }, async (args) => ({
  content: [{ type: "text", text: args.msg }],
}));

export { server };
