# Dawnwalker Lacra Quest Fix

Unofficial Windows save repair utility for a specific broken outcome of
**A Friend Like This** in *The Blood of Dawnwalker*. It targets saves where Nish
was protected, Lacra refused cooperation, and **Song of the Mountain** did not
appear.

## Download and use

Download the latest Windows ZIP from the GitHub Releases page and extract the
whole archive. Keep `Dawnwalker-Lacra-Fix.exe` next to its `_internal` folder.

1. Close the game.
2. Start `Dawnwalker-Lacra-Fix.exe`.
3. Select a manual save and choose **Analyze selected save**.
4. If repair is available, use **Create repaired copy (ADD)**.
5. Load the new slot in game. Keep the original save until you have verified it.

The application opens the normal per-user `SaveGames` directory automatically
when it is available. It works entirely offline and does not upload save data.

## Supported saves and safety

- Windows x64 and manual saves only.
- Supported profiles: `SaveVersion 134` and `136`, with `GameVersion 5` and
  `BuildVersion 258504`. Version 136 was checked against before-quest,
  good-outcome, and broken-outcome samples, and repaired copies from two broken
  saves were confirmed working in game.
- ADD creates a new slot and leaves the source files unchanged.
- PATCH is an advanced in-place mode. It creates a verified backup first.
- Unknown versions, layouts, quest outcomes, and already-progressed saves are
  refused instead of being modified speculatively.

## Building from source

Python 3.11 and [uv](https://docs.astral.sh/uv/) are required.

```powershell
uv sync --extra dev --extra gui --extra build
uv run pytest
.\scripts\build_windows.ps1
```

The source package also exposes an optional `dawnwalker-lacra` CLI for testing,
diagnostics, and backup recovery. It is not needed for the normal portable GUI
workflow.

## License

Copyright (C) 2026 sonervous7.

This project is licensed under GPL-3.0-or-later. See [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This is an independent community project and is not affiliated with or endorsed
by Rebel Wolves or Bandai Namco Entertainment. Game names are used only to
identify compatibility.
