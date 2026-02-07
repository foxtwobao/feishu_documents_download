# VS Code MCP Integration

This workspace registers the `lark_doc_search` MCP server so Codex can query Lark developer docs.

## Prerequisites
- Node.js 20+ with `npx` (installed via `apt-get install nodejs npm`).
- Internet access for `npx` to download the `@larksuiteoapi/lark-mcp` package on first run.

## VS Code Settings
- Workspace: `.vscode/settings.json` defines both `codex.mcpServers` and the plain `mcpServers` entry.
- User scope: `/root/.vscode-server/data/User/mcp.json` replicates the same configuration for remote VS Code sessions.

## Usage
1. Launch Codex in VS Code (Command Palette → `Codex: Connect`).
2. Confirm the `lark_doc_search` server appears in the Codex MCP list.
3. Run a query; Codex will spawn the MCP server via `npx` automatically. The first execution may take longer while packages download.
4. Subsequent calls reuse the cached npm installation.

## Troubleshooting
- If Codex reports `npx` missing, run `node -v` to ensure Node.js installed. Reinstall via `sudo apt-get install nodejs npm` if needed.
- For offline environments, preinstall the package with `npm install -g @larksuiteoapi/lark-mcp` and update the command path accordingly.
