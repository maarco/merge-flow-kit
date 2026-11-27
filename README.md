# merge-flow-kit

Land every ready GitHub pull request in one merge instead of one at a time.

With a strict "branch must be up to date" rule, each merge puts every other open PR behind main, so each one
merges main in and runs CI again. merge-flow plans one merge for all of them:

1. **Precheck.** Each ready PR is merged with main, and every pair of PRs that shares a file is merged with
   `git merge-tree` (seconds, no CI). A clash marks the later PR for a fix, after any fix it depends on.
2. **Pair.** The rest pair up by shared files, level by level, into one combined commit.
3. **Window.** That commit merges onto main as the window. CI runs once on it.

A ready PR is open, not a draft, approved, and passes every required check.

## Dry run

    pip install merge-flow-kit
    cd your-repo
    merge-flow --repo owner/name                       # every ready PR
    merge-flow --repo owner/name --prs 12,15           # just these, in this order
    merge-flow --repo owner/name --checks tests,lint   # only these checks are required

It prints what clashes, which PRs need a fix and in which round, and what lands now. Merges are git objects
only: nothing is pushed and nothing is written to GitHub. Fetched refs go under `refs/merge-flow/`.

## Measured

Replayed on one real repo's 78 merged PRs of one week, all ready at once: one at a time with strict
up-to-date took about 13.6 hours; the flow took about 1.8 hours. 28 of the 78 needed a fix; the longest
fix chain (9 deep) is the floor.

## License

MIT
