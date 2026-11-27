# merge-flow-kit

Land every ready GitHub pull request in one merge instead of one at a time.

With a strict "branch must be up to date" rule, each merge puts every other open PR behind main, so each one
merges main in and runs CI again. merge-flow plans one merge for all of them:

1. **Precheck.** Each ready PR is merged with main, and every pair of PRs that shares a path (the same file, or
   a file and a folder of the same name) is merged with `git merge-tree` (seconds, no CI). A clash marks the
   later PR for a fix, after any fix it depends on.
2. **Pair.** The rest pair up by shared files, level by level, into one combined commit.
3. **Window.** That commit merges onto main as the window. CI runs once on it.

A ready PR is open, not a draft, approved, and passes every required check.

## Dry run

    pip install merge-flow-kit
    cd your-repo
    merge-flow                       # every ready PR of the GitHub repo behind origin
    merge-flow --prs 12,15           # just these, in this order
    merge-flow --checks tests,lint   # only these checks are required
    merge-flow --remote upstream     # another GitHub remote

The default run reads up to 1000 open PRs and stops if it reaches that limit, since the repository may have more.

It prints what clashes, which PRs need a fix and in which round, and what lands now. Merges are git objects
only: nothing is pushed and nothing is written to GitHub. Fetched refs go under `refs/merge-flow/`.

## Landing a window

    merge-flow --open                          # push the window commit, open its PR
    GH_TOKEN=<merging account> merge-flow --land 42

`--open` pushes the planned window commit to `merge-flow/window-<sha>` and opens a PR titled
`chore(merge-flow): land #A, #B` (or a count-based title for windows over GitHub's 256-character limit).
Its body records the base and each landed PR's head, plus one `Refs #N` line for each distinct linked issue.
The window PR adds no change of its own; its checks run once on the combined result.

`--land` merges only if all of these still hold: the base branch has not moved, every listed PR has the head
that was approved and is still ready, the window's checks are green, and rebuilding the window from those
heads gives the same files. `--land` also refuses a window whose history holds anything but clean two-parent
merges of the base and the approved heads. It re-reads the window and source PR state from GitHub after the
local rebuild, immediately before approval. Then it approves and merges the window as one merge commit. The window commit holds
exactly the approved heads, so a PR pushed again after these checks lands at its approved head only; its newer
commits stay open in that PR for their own review. The target branch must require branches to be up to date
before merging (strict required checks) or use a merge queue: `--land` reads the base once, and only GitHub
can refuse a merge when the base moves in the seconds between that read and the merge call. Run it as an account
that did not open the window, since GitHub refuses self-approval. A PR marked for a fix stays out of the
window and goes to its fixer. `--land` prints `landed #N: ...` and exits 0 only after GitHub reports the window
as `MERGED`; if it remains `OPEN` in the merge queue, it reports that it is queued but not merged yet and exits 2.
Any other reported state is printed and exits 1.

## Measured

Replayed on one real repo's 78 merged PRs of one week, all ready at once: one at a time with strict
up-to-date took about 13.6 hours; the flow took about 1.8 hours. 28 of the 78 needed a fix; the longest
fix chain (9 deep) is the floor.

## License

MIT
