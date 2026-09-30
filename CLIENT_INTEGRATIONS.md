# Optional Codex and Claude Code hooks

The hook scripts are optional local integrations. They are not installed or registered by the Link Memory launcher. They send the current prompt text to the local Gateway endpoint for bounded recall, then provide returned context to the coding assistant. The Gateway is configured by default for loopback. Remote provider use is separately controlled by Link Memory configuration.

These snippets are examples. Review the script path, Python interpreter, Gateway key, and client config before adding them. Back up your existing configuration first. Removing the added hook entry disables the integration without uninstalling Link Memory.

## Connect the MCP server for explicit capture and retrieval

The Gateway includes an MCP server exposing tools such as `memory_recall`, `memory_capture`, and `memory_import`. Adding this server lets a supported coding assistant use those tools when you request it. It does not silently save every new conversation. It runs as a local process and talks to the loopback Gateway.

For Codex, merge a server entry into `%USERPROFILE%\\.codex\\config.toml`:

```toml
[mcp_servers.link-memory]
command = "python"
args = ["C:/PATH/TO/link-memory-public-draft/gateway/mcp_server.py"]
```

For Claude Code, merge an entry into the project's `.mcp.json`:

```json
{
  "mcpServers": {
    "link-memory": {
      "type": "stdio",
      "command": "python",
      "args": ["C:/PATH/TO/link-memory-public-draft/gateway/mcp_server.py"]
    }
  }
}
```

Replace the example path with the absolute path on your own machine. Keep existing server entries. Restart the client and explicitly approve the server if prompted. For a remote Gateway, configure the endpoint and key in the MCP process environment using the client's supported secure settings; do not put credentials in a public project configuration file.

For ongoing conversations, ask the assistant to call `memory_capture` with only the conversation content you intend to save. The default keeps a temporary raw copy in the Gateway. Raw-copy deletion must be requested explicitly. This deliberate tool call is the consent action; merely connecting the MCP server does not import or capture prior conversations.

## Codex CLI / Codex desktop

Current Codex hook configuration supports `UserPromptSubmit` command hooks. In the active Codex `config.toml` (normally `%USERPROFILE%\.codex\config.toml`), add a hook entry using an absolute path to this checkout:

```toml
[hooks]
UserPromptSubmit = [
  { hooks = [
    { type = "command", command = "python C:/PATH/TO/link-memory-public-draft/scripts/codex_user_prompt_hook.py" }
  ] }
]
```

If a `[hooks]` section already exists, merge the event into it; do not overwrite other hooks. Restart Codex and review/trust the hook when Codex prompts. Codex may require hooks to be explicitly trusted. Hooks run only in clients that support them; the cloud website does not gain access to a local script merely because this repository is public.

## Claude Code

Claude Code supports command hooks configured in its settings JSON. In `%USERPROFILE%\.claude\settings.json`, merge this event under the top-level `hooks` object:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python \"C:/PATH/TO/link-memory-public-draft/scripts/claude_code_user_prompt_hook.py\""
          }
        ]
      }
    ]
  }
}
```

If the file already has `hooks`, merge only the `UserPromptSubmit` event and keep all existing settings. Restart Claude Code and follow its prompt to review the hook.

## Data sent by a live hook

Each hook sends the current user prompt, bounded to 2,000 characters, to `127.0.0.1` on the Gateway port. The Gateway returns at most three relevant memory items; the hook bounds the context before returning it to the AI client. The scripts fail open if the local Gateway is unavailable. If you change the endpoint or run a remote Gateway, prompts and returned context may leave the computer; review the server and provider settings first.

## Cloud limitation

These are local process hooks. They do not install into ChatGPT/Codex Cloud or Claude.ai, and those hosted services cannot execute a script from your computer using this setup. Use only a supported local client/runtime with access to the checkout and local Gateway.

## Official references

- [Codex hooks](https://developers.openai.com/docs/hooks)
- [Codex MCP configuration](https://developers.openai.com/learn/docs-mcp)
- [Claude Code hooks](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Claude Code MCP](https://docs.anthropic.com/en/docs/claude-code/mcp)
