# EDHelper Technical Audit Roadmap

## Phase 1 – Core Execution Audit

[ ] Event pipeline trace (Journal → Handler → State → UI)
[ ] State model structure validation
[ ] Overview tab data flow audit
[ ] Exploration tab logic audit
[ ] Exobiology tab data dependency audit
[ ] PowerPlay data flow audit
[ ] Combat classification audit
[ ] Intel data source audit
[ ] Materials & Odyssey state audit

## Phase 2 – Consistency Verification

[ ] EstimatedValue injection consistency
[ ] Threshold usage consistency across tabs
[ ] Mapped/unmapped state validation
[ ] Duplicate logic detection across tabs
[ ] Config source verification (all thresholds from settings)

## Phase 3 – Integrity Checks

[ ] JSON data load validation (planet/exo/intel/farming)
[ ] State mutation safety review
[ ] Handler separation verification
[ ] UI render dependency audit

---

Audit Policy:
- No improvements before audit completion
- All findings must reference exact file and function
- No speculative refactoring
- All changes must follow audit documentation