"""The weekly health email needs git history to attribute movement to merged PRs.

`audit_weekly.code_changes_since` runs `git log <built_from_commit>..HEAD`. On the
default depth-1 checkout that range does not exist, git log fails, and every
change a just-merged PR made was flagged as a breakage (2026-09-30, #455). These
pin the fix: the workflow checks out full history, and a failed range warns
instead of passing silently.

Runs under pytest and directly as `python tests/test_health_email_history.py`.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))


def test_health_workflow_checks_out_full_history():
    wf = yaml.safe_load((_ROOT / ".github/workflows/weekly_health_email.yml").read_text())
    steps = wf["jobs"]["health-email"]["steps"]
    co = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert co, "no checkout step"
    assert str((co[0].get("with") or {}).get("fetch-depth")) == "0", \
        "health email checkout must use fetch-depth: 0 (code_changes_since needs history)"


def test_code_changes_since_lists_commits_and_warns_on_a_missing_range(capsys=None):
    import audit_weekly as A
    with tempfile.TemporaryDirectory() as d:
        run = lambda *a: subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
        run("init", "-q")
        run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q",
            "--allow-empty", "-m", "base")
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True,
                              text=True).stdout.strip()
        run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q",
            "--allow-empty", "-m", "A real code change (#999)")
        old_root = A._ROOT
        A._ROOT = Path(d)
        try:
            got = A.code_changes_since(base)
            assert [s for _, s in got] == ["A real code change (#999)"], got
            assert A.code_changes_since("0" * 40) == []      # unknown range -> [] + warning
        finally:
            A._ROOT = old_root


if __name__ == "__main__":
    test_health_workflow_checks_out_full_history()
    test_code_changes_since_lists_commits_and_warns_on_a_missing_range()
    print("ok")
