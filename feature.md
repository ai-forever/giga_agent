# Chat configuration

## Brief
Add a button with "+" icon, popping up a menu with selection of such entities:
- attach a file (respectively, remove a separate button for it in bottom bar)
- "Документы" and toggle menu for them to select. If any selected - show the icon of docs in the bottom bar with amount of document folders selected. when hovering this icon - pop up a list of names of document folders

- "Персонализация" and "Печать" should be removed to: sidebar->account, under "Факты о вас"
- Current "Инструменты" should be renamed to MCP
- There should be a new "Инструменты" menu, that shows all the current tools connected via backend/giga_agent/modules (below more info)

## UI details

### "+" button
- Position: left side of the input area (replaces the current gear icon)
- Opens a dropdown/popover menu with the reorganized items

### "Документы" submenu
- Mirrors the toggles from the original "Документы" page (inline collection toggles inside the dropdown)
- When any collections are selected: show a docs icon in the bottom bar (inside the input area container, next to the "+" button) with the count of selected document folders
- Hovering the docs icon shows a popover with names of selected document folders

### "Персонализация" & "Печать"
- Moved to: sidebar → account dropdown menu, placed under "Факты о вас"

### "Инструменты" (modules tools)
- Shows all tool groups from backend modules as a tree
- One common toggle per module group (all tools in a module toggled together)
- Each tool within a group displays its `about_tool` description
- Toggle state is persisted in user settings (sent with each message)
- Conditional tool groups (those requiring credentials/secrets) are visually marked as such

## Backend

### New endpoint
In `backend/giga_agent/routes/agent.py` — new endpoint to get all available tools from modules.
- Returns ALL modules that can have tools (even if currently unconfigured for the user)
- Modules with conditional tools (depending on credentials) are marked in the response
- Not all modules have tools — only return those that do

### Tool metadata
- For every tool in modules: add an `about_tool` field directly in the tool's extras dict (per-tool, invasive approach on BaseTool instances)
- Short UI-friendly description for each tool
