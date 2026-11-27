"""Merge flow dry run: precheck, fix order and pair-merge tree on a real git repo."""

import json
import subprocess
from pathlib import Path

import pytest

from merge_flow_kit.cli import Head, changed_files, jaccard, plan, ready_prs


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\nfour\nfive\n")
    (tmp_path / "b.txt").write_text("alpha\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _pr(repo: Path, number: int, path: str, text: str) -> Head:
    _git(repo, "checkout", "-q", "-b", f"pr{number}", "main")
    (repo / path).write_text(text)
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", f"pr {number}")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    base = _git(repo, "rev-parse", "main")
    return Head(number, sha, changed_files(repo, base, sha))


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return (
        subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer], check=False).returncode
        == 0
    )


def test_disjoint_prs_land_in_one_window_commit(repo: Path) -> None:
    base = _git(repo, "rev-parse", "main")
    a = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    c = _pr(repo, 3, "b.txt", "ALPHA\n")

    result = plan(repo, base, [a, c])

    assert result["clashes"] == []
    assert result["needs_fix"] == []
    assert result["landed"] == [1, 3]
    window = result["window_commit"]
    assert _is_ancestor(repo, base, window)
    assert _is_ancestor(repo, a.sha, window) and _is_ancestor(repo, c.sha, window)
    assert _git(repo, "show", f"{window}:a.txt").startswith("ONE")
    assert _git(repo, "show", f"{window}:b.txt") == "ALPHA"


def test_a_clash_marks_the_later_pr_for_a_fix_and_the_rest_still_land(repo: Path) -> None:
    base = _git(repo, "rev-parse", "main")
    a = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    b = _pr(repo, 2, "a.txt", "uno\ntwo\nthree\nfour\nfive\n")
    c = _pr(repo, 3, "b.txt", "ALPHA\n")

    result = plan(repo, base, [a, b, c])

    assert [x["prs"] for x in result["clashes"]] == [[1, 2]]
    assert result["clashes"][0]["files"] == ["a.txt"]
    assert result["needs_fix"] == [{"pr": 2, "depth": 1}]
    assert result["landed"] == [1, 3]
    assert not _is_ancestor(repo, b.sha, result["window_commit"])


def test_fixes_chain_when_a_pr_clashes_with_one_that_needs_a_fix(repo: Path) -> None:
    base = _git(repo, "rev-parse", "main")
    a = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    b = _pr(repo, 2, "a.txt", "uno\nTWO\nthree\nfour\nfive\n")
    c = _pr(repo, 3, "a.txt", "one\ndos\nthree\nfour\nfive\n")

    result = plan(repo, base, [a, b, c])

    assert result["needs_fix"] == [{"pr": 2, "depth": 1}, {"pr": 3, "depth": 2}]
    assert result["fix_rounds"] == 2


def test_a_pr_that_clashes_with_main_needs_a_fix(repo: Path) -> None:
    a = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    (repo / "a.txt").write_text("won\ntwo\nthree\nfour\nfive\n")
    _git(repo, "commit", "-q", "-am", "main moves")
    base = _git(repo, "rev-parse", "main")

    result = plan(repo, base, [a])

    assert result["clashes"] == [{"prs": [1], "with": "main", "files": ["a.txt"]}]
    assert result["needs_fix"] == [{"pr": 1, "depth": 1}]
    assert result["landed"] == []
    assert result["window_commit"] is None


def test_prs_that_share_files_pair_first(repo: Path) -> None:
    base = _git(repo, "rev-parse", "main")
    d = _pr(repo, 4, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    f = _pr(repo, 6, "b.txt", "ALPHA\n")
    e = _pr(repo, 5, "a.txt", "one\ntwo\nthree\nfour\nFIVE\n")

    result = plan(repo, base, [d, f, e])

    assert result["levels"][0] == [[4, 5]]
    assert result["landed"] == [4, 5, 6]
    assert _git(repo, "show", f"{result['window_commit']}:a.txt") == "ONE\ntwo\nthree\nfour\nFIVE"


def test_changed_files_ignore_changelog_fragments(repo: Path) -> None:
    base = _git(repo, "rev-parse", "main")
    _git(repo, "checkout", "-q", "-b", "frag", "main")
    (repo / "changes").mkdir()
    (repo / "changes" / "1.added.md").write_text("x\n")
    (repo / "b.txt").write_text("beta\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "frag")

    assert changed_files(repo, base, _git(repo, "rev-parse", "HEAD")) == frozenset({"b.txt"})


def test_jaccard() -> None:
    assert jaccard(frozenset(), frozenset()) == 0.0
    assert jaccard(frozenset({"a", "b"}), frozenset({"b", "c"})) == pytest.approx(1 / 3)


def _check(name: str, state: str) -> dict[str, str]:
    return {"__typename": "StatusContext", "context": name, "state": state}


def test_ready_prs_need_approval_green_required_checks_and_no_draft() -> None:
    green = [_check(name, "SUCCESS") for name in ("ci/tests", "ci/standards-check", "ci/security-scan")]
    items = [
        {"number": 10, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": green},
        {"number": 11, "isDraft": True, "reviewDecision": "APPROVED", "statusCheckRollup": green},
        {"number": 12, "isDraft": False, "reviewDecision": "REVIEW_REQUIRED", "statusCheckRollup": green},
        {"number": 13, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": green[:2]},
        {
            "number": 9,
            "isDraft": False,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [
                {"__typename": "CheckRun", "name": c["context"], "conclusion": "SUCCESS"} for c in green
            ],
        },
        {
            "number": 14,
            "isDraft": False,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [*green[:2], _check("ci/security-scan", "FAILURE")],
        },
    ]

    assert ready_prs(items, ("ci/tests", "ci/standards-check", "ci/security-scan")) == [9, 10]


def test_ready_prs_without_names_require_every_reported_check() -> None:
    items = [
        {"number": 1, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": [_check("a", "SUCCESS")]},
        {
            "number": 2,
            "isDraft": False,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [_check("a", "SUCCESS"), _check("b", "FAILURE")],
        },
        {"number": 3, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": []},
    ]

    assert ready_prs(items) == [1]


def test_a_rerun_that_failed_beats_an_earlier_success_with_the_same_name() -> None:
    def run(state: str, at: str) -> dict[str, str]:
        return {"__typename": "CheckRun", "name": "tests", "conclusion": state, "startedAt": at}

    items = [
        {
            "number": 1,
            "isDraft": False,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [run("SUCCESS", "2026-11-27T10:00:00Z"), run("FAILURE", "2026-11-27T11:00:00Z")],
        },
        {
            "number": 2,
            "isDraft": False,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [run("FAILURE", "2026-11-27T10:00:00Z"), run("SUCCESS", "2026-11-27T11:00:00Z")],
        },
    ]

    assert ready_prs(items, ("tests",)) == [2]


def test_a_rename_still_clashes_with_an_edit_to_the_old_path(repo: Path) -> None:
    base = _git(repo, "rev-parse", "main")
    _git(repo, "checkout", "-q", "-b", "pr1", "main")
    _git(repo, "mv", "a.txt", "new.txt")
    (repo / "new.txt").write_text("ONE\ntwo\nthree\nfour\nfive\n")
    _git(repo, "commit", "-q", "-am", "rename")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    a = Head(1, sha, changed_files(repo, base, sha))
    b = _pr(repo, 2, "a.txt", "uno\ntwo\nthree\nfour\nfive\n")

    result = plan(repo, base, [a, b])

    assert "a.txt" in a.files
    assert result["needs_fix"] == [{"pr": 2, "depth": 1}]
    assert result["held"] == []


def test_github_repo_comes_from_the_remote_url() -> None:
    from merge_flow_kit.cli import github_repo

    assert github_repo("https://github.com/owner/name.git") == "owner/name"
    assert github_repo("https://github.com/owner/name") == "owner/name"
    assert github_repo("git@github.com:owner/name.git") == "owner/name"
    assert github_repo("ssh://git@github.com/owner/name.git") == "owner/name"
    with pytest.raises(ValueError):
        github_repo("https://gitlab.com/owner/name.git")


def test_fetch_writes_only_merge_flow_refs(repo: Path, tmp_path: Path) -> None:
    from merge_flow_kit.cli import fetch

    _git(repo, "tag", "v-probe")
    local = tmp_path / "local"
    local.mkdir()
    _git(local, "init", "-q", "-b", "main")

    fetch(local, str(repo), ["+refs/heads/main:refs/merge-flow/base"])

    assert _git(local, "for-each-ref", "--format=%(refname)") == "refs/merge-flow/base"
    assert not (local / ".git" / "FETCH_HEAD").exists()


def test_a_head_already_on_main_does_not_land(repo: Path) -> None:
    base = _git(repo, "rev-parse", "main")

    result = plan(repo, base, [Head(7, base)])

    assert result["landed"] == []
    assert result["already_on_base"] == [7]
    assert result["window_commit"] is None


def test_verify_accepts_the_planned_window_and_rejects_anything_else(repo: Path) -> None:
    from merge_flow_kit.cli import verify

    base = _git(repo, "rev-parse", "main")
    a = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    c = _pr(repo, 3, "b.txt", "ALPHA\n")
    window = plan(repo, base, [a, c])["window_commit"]

    assert verify(repo, base, {1: a.sha, 3: c.sha}, window) == []

    _git(repo, "checkout", "-q", "--detach", window)
    (repo / "b.txt").write_text("sneaky\n")
    _git(repo, "commit", "-q", "-am", "extra change")
    extra = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    assert verify(repo, base, {1: a.sha, 3: c.sha}, extra) != []

    moved = _pr(repo, 7, "b.txt", "OTHER\n")
    assert verify(repo, base, {1: a.sha, 3: moved.sha}, window) != []


def test_window_body_round_trips_the_landed_heads() -> None:
    from merge_flow_kit.cli import parse_window_body, window_body

    body = window_body("abc123", {1450: "f00", 1458: "ba7"})

    assert "#1450" in body and "#1458" in body
    assert parse_window_body(body) == ("abc123", {1450: "f00", 1458: "ba7"})
    assert parse_window_body("no marker here") is None


def test_green_uses_the_newest_run_and_every_check_by_default() -> None:
    from merge_flow_kit.cli import green

    old_pass = {"__typename": "CheckRun", "name": "t", "conclusion": "SUCCESS", "startedAt": "1"}
    new_fail = {"__typename": "CheckRun", "name": "t", "conclusion": "FAILURE", "startedAt": "2"}

    assert green([old_pass], ())
    assert not green([old_pass, new_fail], ())
    assert not green([], ())
    assert not green([old_pass], ("t", "lint"))


_GREEN = [{"__typename": "CheckRun", "name": "ci", "conclusion": "SUCCESS", "startedAt": "2026-11-27T10:00:00Z"}]


def _land_setup(repo: Path, monkeypatch: pytest.MonkeyPatch, view: dict) -> list:
    """A planned window for PR 1 with refs/merge-flow/* in place and every GitHub call stubbed."""
    from merge_flow_kit import cli

    base = _git(repo, "rev-parse", "main")
    a = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    window = plan(repo, base, [a])["window_commit"]
    for ref, sha in (("base", base), ("pr/1", a.sha), ("window", window)):
        _git(repo, "update-ref", f"refs/merge-flow/{ref}", sha)
    calls: list[tuple[str, ...]] = []
    pr = {"body": cli.window_body(base, {1: a.sha}), "statusCheckRollup": _GREEN, "state": "OPEN"}
    pr |= {"baseRefName": "main", "headRefOid": window} | view

    def gh(*args: str) -> str:
        if args[:2] == ("pr", "view"):
            if args[-2:] == ("--json", "state"):
                calls.append(args)
                return json.dumps({"state": view.get("postMergeState", "MERGED")})
            return json.dumps(pr)
        calls.append(args)
        return ""

    ready = [{"number": 1, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": _GREEN}]
    ready[0] |= {"baseRefName": view.get("sourceBase", "main"), "headRefOid": view.get("sourceHead", a.sha)}
    if "sourceApproved" in view:
        ready[0]["approvedCommits"] = view["sourceApproved"]
    monkeypatch.setattr(cli, "_gh", gh)
    monkeypatch.setattr(cli, "_gh_open_prs", lambda _repo: ready)
    monkeypatch.setattr(cli, "fetch", lambda *_args: None)
    return calls


def test_land_merges_with_the_checked_head_pinned(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from merge_flow_kit.cli import land_window

    calls = _land_setup(repo, monkeypatch, {})

    assert land_window(repo, "origin", "o/r", "main", 42, ()) == 0
    merge = next(c for c in calls if c[:2] == ("pr", "merge"))
    assert merge[merge.index("--match-head-commit") + 1] == _git(repo, "rev-parse", "refs/merge-flow/window")


def test_land_reports_a_queued_window_as_not_landed(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from merge_flow_kit.cli import land_window

    calls = _land_setup(repo, monkeypatch, {"postMergeState": "OPEN"})

    assert land_window(repo, "origin", "o/r", "main", 42, ()) == 2
    output = capsys.readouterr().out
    assert "queued" in output
    assert "not merged yet" in output
    assert "landed" not in output
    assert ("pr", "view", "42", "--repo", "o/r", "--json", "state") in calls


def test_land_refuses_a_window_pr_that_targets_another_branch(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from merge_flow_kit.cli import land_window

    calls = _land_setup(repo, monkeypatch, {"baseRefName": "release"})

    assert land_window(repo, "origin", "o/r", "main", 42, ()) == 1
    assert calls == []


def test_land_refuses_when_the_window_head_moved_after_its_checks(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from merge_flow_kit.cli import land_window

    calls = _land_setup(repo, monkeypatch, {})
    window = _git(repo, "rev-parse", "refs/merge-flow/window")
    parents = _git(repo, "rev-list", "--parents", "-n", "1", window).split()[1:]
    twin = _git(repo, "commit-tree", f"{window}^{{tree}}", *[x for p in parents for x in ("-p", p)], "-m", "same files")
    _git(repo, "update-ref", "refs/merge-flow/window", twin)

    assert land_window(repo, "origin", "o/r", "main", 42, ()) == 1
    assert calls == []


def test_a_queued_rerun_without_a_start_time_is_not_green() -> None:
    old_pass = {"__typename": "CheckRun", "name": "tests", "conclusion": "SUCCESS", "startedAt": "2026-11-27T10:00:00Z"}
    queued = {"__typename": "CheckRun", "name": "tests", "conclusion": None, "status": "QUEUED", "startedAt": None}
    item = {"number": 42, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": [old_pass, queued]}

    assert ready_prs([item], ("tests",)) == []


def test_ready_prs_only_counts_prs_into_the_base_branch() -> None:
    def item(number: int, base: str) -> dict:
        green = [_check("ci", "SUCCESS")]
        return {"number": number, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": green} | {
            "baseRefName": base
        }

    assert ready_prs([item(1, "main"), item(2, "release")], (), "main") == [1]


def test_land_refuses_a_source_pr_that_targets_another_branch(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from merge_flow_kit.cli import land_window

    calls = _land_setup(repo, monkeypatch, {"sourceBase": "release"})

    assert land_window(repo, "origin", "o/r", "main", 42, ()) == 1
    assert calls == []


def test_verify_rejects_a_window_that_brings_in_an_unlisted_commit(repo: Path) -> None:
    from merge_flow_kit.cli import verify

    base = _git(repo, "rev-parse", "main")
    a = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    unlisted = _pr(repo, 9, "c.txt", "not approved\n")
    window = plan(repo, base, [a])["window_commit"]
    smuggled = _git(
        repo, "commit-tree", f"{window}^{{tree}}", "-p", base, "-p", window, "-p", unlisted.sha, "-m", "extra parent"
    )

    assert verify(repo, base, {1: a.sha}, smuggled) != []


def test_land_refuses_when_a_source_pr_moved_after_the_fetch(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from merge_flow_kit.cli import land_window

    calls = _land_setup(repo, monkeypatch, {"sourceHead": "f" * 40})

    assert land_window(repo, "origin", "o/r", "main", 42, ()) == 1
    assert calls == []


def test_an_approval_counts_only_on_the_head_it_was_given_for() -> None:
    item = {"number": 5, "isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": [_check("ci", "SUCCESS")]}

    assert ready_prs([item | {"headRefOid": "b", "approvedCommits": ["a"]}]) == []
    assert ready_prs([item | {"headRefOid": "b", "approvedCommits": ["a", "b"]}]) == [5]


def test_land_refuses_a_head_nobody_approved(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from merge_flow_kit.cli import land_window

    calls = _land_setup(repo, monkeypatch, {"sourceApproved": ["0" * 40]})

    assert land_window(repo, "origin", "o/r", "main", 42, ()) == 1
    assert calls == []


def test_the_plan_skips_a_pr_that_moved_after_it_was_listed_ready(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from merge_flow_kit import cli

    base = _git(repo, "rev-parse", "main")
    listed = _pr(repo, 1, "a.txt", "ONE\ntwo\nthree\nfour\nfive\n")
    moved = _pr(repo, 2, "b.txt", "BETA\n")
    _git(repo, "remote", "add", "origin", "https://github.com/o/r.git")
    item = {"isDraft": False, "reviewDecision": "APPROVED", "statusCheckRollup": [_check("ci", "SUCCESS")]}
    item |= {"baseRefName": "main"}
    items = [item | {"number": 1, "headRefOid": listed.sha}, item | {"number": 2, "headRefOid": "f" * 40}]

    def fetch(root: Path, _remote: str, _refspecs: list[str]) -> None:
        for ref, sha in (("base", base), ("pr/1", listed.sha), ("pr/2", moved.sha)):
            _git(root, "update-ref", f"refs/merge-flow/{ref}", sha)

    monkeypatch.setattr(cli, "_gh_open_prs", lambda _repo: items)
    monkeypatch.setattr(cli, "fetch", fetch)
    monkeypatch.chdir(repo)
    out = tmp_path / "plan.json"

    assert cli.main(["--json", str(out)]) == 0
    assert json.loads(out.read_text())["prs"] == [1]


def test_github_repo_needs_github_com_as_the_host() -> None:
    from merge_flow_kit.cli import github_repo

    for url in ("https://notgithub.com/o/r.git", "https://github.com.evil.example/o/r", "git@evilgithub.com:o/r"):
        with pytest.raises(ValueError):
            github_repo(url)
