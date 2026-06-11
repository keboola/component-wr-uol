#!/usr/bin/env python3
"""
Regenerate VCR cassettes (logs.json + requests.json) for selected tests by running
the component in record mode directly against the source data directories.

Suppresses the component SDK's own VCR replay layer (same technique as VCRTestDataDir)
so the recorded tracebacks match what the test runner would capture.
"""

import os
import re
import sys
from pathlib import Path
from runpy import run_path

repo_root = Path(__file__).resolve().parent.parent
# Ensure component src is importable (needed when running component.py via run_path)
sys.path.insert(0, str(repo_root / "src"))

from keboola.vcr.recorder import VCRRecorder  # noqa: E402

FUNCTIONAL_DIR = repo_root / "tests" / "functional"
COMPONENT_SCRIPT = str(repo_root / "src" / "component.py")


def _suppress_sdk_vcr():
    """Prevent ComponentBase from creating its own VCR replay layer.

    Returns a callable that restores the original state.
    """
    try:
        from keboola.component.base import ComponentBase

        if hasattr(ComponentBase, "_should_vcr_replay"):
            original = ComponentBase._should_vcr_replay
            ComponentBase._should_vcr_replay = staticmethod(lambda: False)
            return lambda: setattr(ComponentBase, "_should_vcr_replay", original)
    except ImportError:
        pass
    return lambda: None


def record_test(test_name: str) -> dict:
    test_data_dir = FUNCTIONAL_DIR / test_name / "source" / "data"
    cassette_dir = test_data_dir / "cassettes"

    print(f"\n--- Recording: {test_name} ---")

    before = {}
    for fname in ["logs.json", "requests.json", "expected_status.json"]:
        p = cassette_dir / fname
        before[fname] = p.read_text() if p.exists() else None

    # Build log normalizers (strip repo-root prefix from tracebacks, same as VCRTestDataDir)
    script_dir = str(Path(COMPONENT_SCRIPT).resolve().parent.parent) + "/"
    log_normalizers = [(re.escape(script_dir), "")]

    recorder = VCRRecorder.from_test_dir(
        test_data_dir=test_data_dir,
        freeze_time_at=None,
        log_normalizers=log_normalizers,
    )

    restore_sdk_vcr = _suppress_sdk_vcr()

    def run_component():
        os.environ["KBC_DATADIR"] = str(test_data_dir)
        run_path(COMPONENT_SCRIPT, run_name="__main__")

    try:
        recorder.record(run_component)
    finally:
        restore_sdk_vcr()

    changes = []
    for fname in ["logs.json", "requests.json", "expected_status.json"]:
        p = cassette_dir / fname
        after = p.read_text() if p.exists() else None
        if after != before[fname]:
            changes.append(fname)
            print(f"  Updated: {fname}")
        else:
            print(f"  Unchanged: {fname}")

    return {"test": test_name, "changes": changes}


def main(tests=None):
    if tests is None:
        tests = [
            "05_bad_json_nested_column",
            "09_upsert_on_create_only_endpoint",
        ]
    results = [record_test(t) for t in tests]
    print("\n=== Summary ===")
    for r in results:
        print(f"  {r['test']}: changed={r['changes'] or 'none'}")


if __name__ == "__main__":
    selected = sys.argv[1:] if len(sys.argv) > 1 else None
    main(selected)
