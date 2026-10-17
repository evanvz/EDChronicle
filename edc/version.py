# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""The app's version: EDDN softwareVersion and every outgoing User-Agent.
Bump it whenever what we send changes (eddnvalid.weslocke.com grades per version).
1.0.1: EDDN horizons/odyssey flags + codexentry/1.
1.0.2: identical journal messages (the game writes some Scans twice) sent once."""

APP_VERSION = "1.0.2"
USER_AGENT = f"EDChronicle/{APP_VERSION} (+https://github.com/evanvz/EDChronicle)"
