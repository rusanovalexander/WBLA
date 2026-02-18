#!/usr/bin/env python3
"""
Run Credit Pack evaluation cases and write results for quality review.

Usage (from credit-pack directory):
  uv run python eval/run_eval.py
  uv run python eval/run_eval.py --case case_01_analyze_short_teaser
  uv run python eval/run_eval.py --output-dir eval/results

Results are written to eval/results/ (or --output-dir):
  - result_<case_id>.json  — full tool outputs per step
  - summary.txt            — pass/fail and key fields
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Run from credit-pack directory so credit_pack is importable
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from credit_pack import tools as credit_pack_tools


def load_cases(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class MockToolContext:
    def __init__(self):
        self.state = {}


async def run_case(case: dict) -> dict:
    """Run one eval case; return { step_name: tool_result, ... }."""
    ctx = MockToolContext()
    results = {"case_id": case["id"], "name": case["name"], "steps_done": [], "outputs": {}}
    inputs = case.get("inputs") or {}

    step_handlers = {
        "set_teaser": (credit_pack_tools.set_teaser, ["teaser_text"]),
        "set_example": (credit_pack_tools.set_example, ["example_text"]),
        "analyze_deal": (credit_pack_tools.analyze_deal, ["teaser_text"]),
        "discover_requirements": (credit_pack_tools.discover_requirements, ["analysis_text"]),
        "check_compliance": (credit_pack_tools.check_compliance, ["requirements_json"]),
        "generate_structure": (credit_pack_tools.generate_structure, ["example_text"]),
        "draft_section": (credit_pack_tools.draft_section, ["section_name"]),
        "export_credit_pack": (credit_pack_tools.export_credit_pack, ["filename"]),
    }

    for step in case.get("steps", []):
        if step not in step_handlers:
            results["outputs"][step] = {"error": f"Unknown step: {step}"}
            continue
        handler, arg_names = step_handlers[step]
        kwargs = {"tool_context": ctx}
        for name in arg_names:
            key = name  # e.g. teaser_text
            if step == "draft_section" and name == "section_name":
                key = "draft_section_name"
            if key in inputs:
                kwargs[name] = inputs[key]
            elif name == "teaser_text":
                kwargs[name] = inputs.get("teaser_text", "")
            elif name == "analysis_text":
                kwargs[name] = inputs.get("analysis_text", "")
            elif name == "requirements_json":
                kwargs[name] = inputs.get("requirements_json", "")
            elif name == "example_text":
                kwargs[name] = inputs.get("example_text", "")
            elif name == "section_name":
                kwargs[name] = inputs.get("draft_section_name", "Executive Summary")
            elif name == "filename":
                kwargs[name] = inputs.get("export_filename", "")
        try:
            out = await handler(**kwargs)
            results["steps_done"].append(step)
            # Truncate very long fields for readability
            if isinstance(out, dict):
                out = out.copy()
                for key in ("thinking", "preview", "message"):
                    if key in out and isinstance(out[key], str) and len(out[key]) > 2000:
                        out[key] = out[key][:2000] + "\n... [truncated]"
            results["outputs"][step] = out
        except Exception as e:
            results["outputs"][step] = {"status": "error", "message": str(e), "exception": type(e).__name__}
    return results


def evaluate_results(case: dict, results: dict) -> list[str]:
    """Return list of check results (ok/FAIL) for human review."""
    lines = []
    checks = case.get("checks") or {}
    outputs = results.get("outputs") or {}
    for step, expected_keys in checks.items():
        # step is e.g. "after_analyze_deal" -> we need output of "analyze_deal"
        tool_step = step.replace("after_", "")
        out = outputs.get(tool_step)
        if not out:
            lines.append(f"  [FAIL] {step}: no output")
            continue
        if not isinstance(out, dict):
            lines.append(f"  [FAIL] {step}: output is not dict")
            continue
        missing = [k for k in expected_keys if k not in out]
        if missing:
            lines.append(f"  [FAIL] {step}: missing keys: {missing}")
        else:
            lines.append(f"  [OK]   {step}: has {expected_keys}")
        if out.get("status") == "error" and case.get("expect_error_step") != tool_step:
            lines.append(f"  [NOTE] {step}: status=error — {out.get('message', '')[:100]}")
    return lines


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run Credit Pack eval cases and write results")
    parser.add_argument("--case", default=None, help="Run only this case id")
    parser.add_argument("--output-dir", default=None, help="Results directory (default: eval/results)")
    parser.add_argument("--list", action="store_true", help="List case ids and exit")
    args = parser.parse_args()

    eval_dir = Path(__file__).resolve().parent
    cases_path = eval_dir / "test_cases.json"
    if not cases_path.exists():
        print("Missing eval/test_cases.json")
        sys.exit(1)
    data = load_cases(cases_path)
    cases = data.get("cases", [])

    if args.list:
        for c in cases:
            print(c["id"], "-", c["name"])
        return

    out_dir = Path(args.output_dir) if args.output_dir else eval_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print("Case not found:", args.case)
            sys.exit(1)

    summary_lines = [
        f"Credit Pack Eval — {datetime.now().isoformat()}",
        f"Cases run: {len(cases)}",
        "",
    ]

    for case in cases:
        print("Running", case["id"], "...", end=" ", flush=True)
        try:
            results = asyncio.run(run_case(case))
        except Exception as e:
            print("Exception:", e)
            results = {"case_id": case["id"], "error": str(e), "outputs": {}}
        out_path = out_dir / f"result_{case['id']}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        print("->", out_path.name)

        check_lines = evaluate_results(case, results)
        summary_lines.append(f"## {case['id']} — {case['name']}")
        summary_lines.extend(check_lines)
        summary_lines.append("")

    summary_path = out_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
    print("Summary:", summary_path)
    print("\nReview result_*.json and summary.txt to assess agent quality.")


if __name__ == "__main__":
    main()
