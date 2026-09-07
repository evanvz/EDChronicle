# EDChronicle

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bobrogers_solo)

EDChronicle is a Python desktop companion app for Elite Dangerous, built for the solo player. It watches your live journal, imports your journal history into a local database, and pulls in community data (Spansh, EDSM, Canonn, EDDN) to fill in the gaps — covering Exploration, Exobiology, Combat, PowerPlay, BGS/Player Faction tracking, Trading, Mining, Engineering, and Fleet Carriers.

Inspired by [EDCoPilot](https://www.razzafrag.com/) by CMDR RazzaFrag.

## Features

- **Exploration** — live body/signal tracking, first-discovery/mapping/footfall status, ring hotspot tracking, Spansh backfill for missing physical stats, Canonn Codex intel
- **Exobiology** — genus/species/sample tracking, estimated credit values, Codex logging
- **Combat** — combat contacts table with real Crime & Punishment engage-risk detection, gated voice callouts (never your own faction/power), notoriety and bounty tracking, massacre-mission stacking, System Status (wars, RES sites) for nearby systems
- **PowerPlay** — live system-type detection, PowerPlay Target Finder cross-checked against two independent data sources, megaship alerts
- **Player Faction (BGS)** — tracks your squadron-aligned faction galaxy-wide (not just where you've been), risk-bucket dashboard (War/Expansion/Retreat/Conflict), Inara CSV import, per-system BGS history and forecasting
- **Market & Trading** — galaxy-wide best price search, Trade Opportunities, Trade Route Loop Planner, rare goods finder, broker/service finder (Black Market, Interstellar Factors, Material Trader, etc.)
- **Mining** — session stats, ring/hotspot finder, sell-price lookup for refined cargo
- **Engineering** — live material inventory, blueprint wishlist with real per-grade roll costs, Material Trader advisor, engineer distance/rank lookup
- **Fleet Carrier** — cargo/jump status tracking, squadron vs. personal carrier separation
- **Voice** — trigger-phrase ship commands and tab navigation (offline recognition), TTS announcements for key events
- **Overview HUD** — single-screen summary of current system, active signals, and recommended actions

Full feature list, architecture, and database schema: see [ARCHITECTURE.md](ARCHITECTURE.md).

## Screenshots

![Overview HUD](docs/screenshots/OverView%20Hud.png)
![Exploration](docs/screenshots/Exploration.png)
![Planets](docs/screenshots/Planets.png)
![Exobiology](docs/screenshots/Exobiology.png)
![Combat](docs/screenshots/Combat.png)
![PowerPlay](docs/screenshots/PowerPlay.png)
![Settings](docs/screenshots/Settings.png)

## How it works

EDChronicle reads your Elite Dangerous journal files live while you play, and imports your full journal history into a local SQLite database on first launch. For data your own journals can't provide — galaxy-wide market prices, station info, PowerPlay control, squadron faction presence elsewhere in the galaxy — it draws on the same shared community network the rest of the Elite Dangerous tooling ecosystem uses: [Spansh](https://spansh.co.uk), [EDSM](https://www.edsm.net), [Canonn](https://canonn.tech), and a live [EDDN](https://github.com/EDCD/EDDN) feed. It can optionally contribute your own journal/market data back to EDDN too (on by default, matching EDMarketConnector's own default).

> **The longer EDChronicle stays open, the better it gets.** Galaxy-wide data (market prices, station services, squadron faction presence elsewhere) only accumulates while the app is running and connected to EDDN — a fresh install starts with none of it. Leave the app open while you play (not just while actively looking at it) to let it build up over time, the same way every EDDN-based tool works.

## Installation

Requires Python 3.10 or later — download from [python.org](https://www.python.org/downloads/).

1. Download or clone this repository
2. From the project root, run:

```
install.bat
```

This creates a Python virtual environment and installs all dependencies. Safe to run more than once.

## Running the application

```
launch.bat
```

Double-click `launch.bat` from anywhere — it always resolves paths relative to the project folder.

> **First launch:** EDChronicle imports all your existing journal files on first run — can take a minute or two, with progress shown on the startup screen. Subsequent launches only process new journals and are fast.

## Updating

```
git pull
install.bat
```

`install.bat` is safe to re-run — it won't recreate the virtual environment, only install newly added dependencies.

## Feedback, suggestions and issues

Have a feature request, found a bug, or want to suggest an improvement?

Open an issue on GitHub: [github.com/evanvz/EDChronicle/issues](https://github.com/evanvz/EDChronicle/issues)

## Support the project

EDChronicle is free and open-source. If it adds value to your gameplay, a coffee is always appreciated.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/bobrogers_solo)

## A note on indie development

This project is built and maintained by a solo developer in personal time. If you use, share, or build on EDChronicle, please respect the work that went into it:

- Credit the original project and author in any derivative work
- Do not redistribute modified versions without clearly noting the changes made
- A link back to this repository is always appreciated

## License

[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) — free to use, study, modify, and share for any noncommercial purpose (personal use, hobby projects, research, education, and similar). Commercial use — selling it, selling derivatives, or using it in a paid product or service — is not permitted without the copyright holder's permission.

Copyright © 2026 CMDR B0B R0GERS

See [LICENSE](LICENSE) for the full license text.
