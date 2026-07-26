---
name: gmail-capability
description: Query, read, search, and send emails from user's Gmail / Avaya account globally across any workspace or project.
---

# Gmail Global Skill

This skill allows Antigravity to interact with the user's Gmail / Avaya email inbox in any workspace or project.

## Capabilities

1. **Search Emails**:
   Use native MCP tool `gmail_search(query)` or run fallback script:
   `python %USERPROFILE%\.gemini\tools\gmail\gmail_mcp_server.py search "<query>"`
   Example queries: `"is:unread"`, `"from:boss@avaya.com"`, `"subject:INC7431659"`

2. **Read Email**:
   Use native MCP tool `gmail_read(message_id)` or run fallback script:
   `python %USERPROFILE%\.gemini\tools\gmail\gmail_mcp_server.py read "<message_id>"`

3. **Send Email**:
   Use native MCP tool `gmail_send(to, subject, body)` or run fallback script:
   `python %USERPROFILE%\.gemini\tools\gmail\gmail_mcp_server.py send "<to>" "<subject>" "<body>"`

## MCP Tools
When the `gmail` MCP server is active in Antigravity, use native tools:
- `gmail_search(query)`
- `gmail_read(message_id)`
- `gmail_send(to, subject, body)`
