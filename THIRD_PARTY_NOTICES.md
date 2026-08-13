# Third-Party Notices

EDChronicle reuses data/logic from the following MIT-licensed community
projects. Their copyright and permission notices are reproduced below as
required by the MIT License.

## msarilar/EDEngineer

https://github.com/msarilar/EDEngineer

Used for: Material Trader grouping/grade data and trade-ratio formulas
(`edc/core/material_trading.py`, `edc/core/odyssey_material_source.py`),
and Engineer-per-blueprint coverage joined into
`settings/engineering_blueprints.json`.

```
MIT License

Copyright (c) 2016 Max

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## jixxed/ed-odyssey-materials-helper

https://github.com/jixxed/ed-odyssey-materials-helper

Used for: Odyssey suit/weapon grade and module material requirements
ported into `settings/odyssey_engineering.json`.

```
Copyright (c) 2026 Jixxed

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Frontier game data (not MIT)

`EDCD/coriolis-data` and `EDCD/FDevIDs` are also used as sources for
blueprint/material/rare-commodity reference data
(`edc/core/engineering_blueprints.py`, `edc/core/rare_commodities.py`,
`settings/engineering_blueprints.json`). This is Frontier Developments'
own game data, not separately licensed by EDCD (coriolis-data's
`LICENSE.md` says its JSON data is Frontier's IP; FDevIDs carries no
license file at all). Use here relies on Frontier's Fan Content Policy
for non-commercial community tools, not an open-source license grant.

## settings/engineer_requirements.json (not from an upstream project)

Unlike the other reference files above, this one wasn't ported from a
specific named open-source project. It's a compilation of each
Engineer's discover/meet/unlock/referral requirements, supplied directly
in the development session rather than sourced from a single upstream
repository. The underlying facts are publicly-known Elite Dangerous game
mechanics — the same information already documented across many
community wikis and official sources (e.g. the Elite Dangerous Wiki's
"Engineers" article) — not proprietary to any one project.
