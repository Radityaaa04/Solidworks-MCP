# SolidWorks MCP validation — 2026-11-01

See [REPORT.md](REPORT.md) for the executed audit, measured results, limitations, and priority findings.

All run evidence and CAD artifacts are in:

```text
D:\New folder (2)\solidworks_mcp_validation_20261101_204158_cc3d1b
```

Production Python source was hashed before and after the run and did not change. These scripts add tests only; no dependency was installed. They use the project's Python 3.11 virtual environment and `unittest`/standard-library tooling rather than pytest.

## Scripts

| Script | Scope |
|---|---|
| `offline_core.py` | Mocked units, document save/close, client connection, geometric validation, STA queue/retry/cancellation/stop |
| `offline_domains.py` | Mocked inspection, equations, assembly, drawing, material, isolated filesystem fixtures |
| `protocol_contract.py` | Real guarded stdio handshake/discovery/validation; mock forwarding for all 48 wrappers; schema/documentation checks |
| `live_validation.py` | First bounded live MCP run and common harness |
| `live_retest.py` | Repeats live tests with an independent baseline and disposable failed-SaveAs fixture |
| `live_followup.py` | Follow-up evidence for parameters, visible/preselected edges, dimensions, projection, configurations |
| `live_final_checks.py` | Final independent controls, first-angle fixture, configuration readback, and audit-only cleanup |
| `summarize_results.py` | Aggregates this audit snapshot, deduplicates live scenarios, checks hashes/syntax/exports, generates the report |

## Important execution notes

- The current commands and exit codes are recorded in each suite's JSON report and the live `live_execution.json` files.
- Test exit code `1` means assertions failed. Do not convert failures into passes by changing production behavior or discarding meaningful tests.
- This is a recorded audit snapshot, not a generic CI runner. Use a fresh output directory beneath the explicitly authorized `D:\New folder (2)` for another audit. The live scripts refuse to overwrite their run subdirectories.
- Do not interact with SolidWorks while live tests are running. Tools operate on active documents.
- Native COM in the follow-up prepares selection/configuration/sheet fixtures and reads independent evidence only after verifying the active saved path belongs to the fresh audit directory. Tested feature/mate/view operations still use the real MCP server.
- Never reproduce destructive cancellation/rollback fault injection on a user's real designs. Those cases are deliberately mocked.
- Raw R1/R2/R3 evidence is retained, including test-harness defects and fixture cascades. The report uses the latest corrected result per scenario and does not mislabel those harness defects as production bugs.
- All 48 tools returning success at least once is entry-point coverage, not proof that every parameter combination or engineering result is correct.
