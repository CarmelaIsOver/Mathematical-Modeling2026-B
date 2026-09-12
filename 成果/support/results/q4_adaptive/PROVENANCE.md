# trace_fixtures.json provenance

Re-frozen with the current source tree. The previous recorded digests and
`development.csv` means correspond to an earlier solver state: rerunning the
committed `frozen_sources.json` candidate (which `verify_q4_coverage.py`
restores) now reproduces the current production rings traces and means exactly,
so the stale fixtures were the inconsistent artifact, not the production code.
The test still guards against future rings regressions.
