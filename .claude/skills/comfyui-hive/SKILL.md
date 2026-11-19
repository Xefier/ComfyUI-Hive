---
name: comfyui-hive
description: Add, remove or list the ComfyUI-Hive rigs that Claude Code on this PC can make images and videos on (the comfyui-hive MCP server), or unregister it. Use when the user runs /comfyui-hive, or asks to register, add, remove or list a ComfyUI rig, e.g. "add 192.168.1.189" or "register the rig at 192.168.1.232".
---

# comfyui-hive: manage this PC's rigs

The commands live in this repository's `client` folder and change the current Windows user's Claude Code config, so
they apply to every project on this PC.

Run it with the PowerShell tool from the repository root (the folder that holds `client\` and `comfyui-hive\`):

```powershell
& .\client\comfyui-hive.cmd <action> <address>[:port] ...
```

| What the user asked | Action |
|---|---|
| Add or register a rig | `add 192.168.1.189` (the page's port 8189 unless they gave one) |
| Remove a rig | `remove 192.168.1.189` |
| Which rigs, or is it working | `list` |
| Remove everything | `unregister` (ask first: it removes every rig) |

With no address given for `add` or `remove`, ask for it. Several addresses can follow one action.

Then tell the user what the output says: each rig's address, whether it answers, and which models are downloaded on
it. A rig "not answering now" is fine if it is on another flight sheet; one with no model downloaded needs someone to
press Download on its page first. The tools `comfy_status`, `comfy_generate`, `comfy_result` and `comfy_cancel` appear
in new sessions only, not in the one that ran the command.

If it fails, report the message as it is. "Claude Code (claude) was not found" or "Python 3.8 or newer was not found"
means that has to be installed first; nothing was changed.
