# Eval results

Sample result files for error-handling cases (case_05, case_06) are included. Full runs overwrite these.

After running:

```bash
cd credit-pack
uv run python eval/run_eval.py
```

you will see:

- **`result_<case_id>.json`** — Full tool outputs for each step (status, summary, thinking, etc.). Use these to judge quality of agent responses (analysis, requirements, compliance, structure, drafts).
- **`summary.txt`** — Quick pass/fail: which cases have the expected keys (e.g. `process_path`, `origination_method`, `total`, `checks_count`).

## Cases (full process coverage)

| Case | Steps | Purpose |
|------|--------|---------|
| case_01 | set_teaser → analyze_deal | Analyze short teaser |
| case_02 | + discover_requirements | Requirements discovery |
| case_03 | + check_compliance | Through compliance |
| case_04 | + generate_structure → draft_section | Structure and one draft |
| case_05 | analyze_deal only | Error: no teaser |
| case_06 | discover_requirements only | Error: no analysis |
| case_07 | set_teaser, **set_example**, analyze → … → draft_section | Full flow with example doc for structure style |
| case_08 | Full flow through **export_credit_pack** | End-to-end including DOCX export |
| case_09 | check_compliance only | Error: no requirements |
| case_10 | generate_structure only | Error: no analysis |
| case_11 | draft_section only | Error: no structure |
| case_12 | export_credit_pack only | Error: no drafts |

## Quality checklist (manual)

When reviewing agent quality, check:

1. **case_01** — `process_path` and `origination_method` non-empty and plausible (e.g. DPF / amendment).
2. **case_02** — Requirements `total` > 0; `filled` reflects RAG/governance pre-fill.
3. **case_03** — Compliance `checks_count` > 0.
4. **case_04** — Structure has sections; draft has non-empty `preview`.
5. **case_05, 06, 09, 10, 11, 12** — Return `status: error` and clear `message`.
6. **case_07** — set_example stored; structure/draft use example style where applicable.
7. **case_08** — Export returns `status: success` and `path` to generated DOCX.

Run a single case:

```bash
uv run python eval/run_eval.py --case case_01_analyze_short_teaser
```

List cases:

```bash
uv run python eval/run_eval.py --list
```
