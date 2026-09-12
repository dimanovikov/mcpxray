"""Shape used by modelcontextprotocol/servers `git` and `time`:
low-level Server, tool names from an enum, schema built by a model."""

from enum import Enum

from mcp.server import Server
from mcp.types import Tool


class GitTools(str, Enum):
    STATUS = "git_status"
    DIFF_UNSTAGED = "git_diff_unstaged"
    COMMIT = "git_commit"


server = Server("mcp-git")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=GitTools.STATUS,
            description="Shows the working tree status",
            inputSchema=GitStatus.model_json_schema(),
        ),
        Tool(
            name=GitTools.DIFF_UNSTAGED.value,
            description="Shows changes not yet staged",
            inputSchema=GitDiffUnstaged.model_json_schema(),
        ),
        Tool(
            name=GitTools.COMMIT,
            description="Records changes to the repository",
            inputSchema=GitCommit.model_json_schema(),
        ),
    ]
