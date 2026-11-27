# Changelog

## Unreleased

- GitHub Action (`action.yml`): `uses: maarco/merge-flow-kit@<ref>` runs `plan`, `open` or `land` in any repository's workflow.
- `--open` uses a Conventional Commit title and adds references to linked issues in its window PR body.
- `merge-flow` dry run: precheck with `git merge-tree`, fix order, similarity pairing, one window commit.
- `--open` pushes the window and opens its PR; `--land` re-verifies it against GitHub and git, then approves and merges it.
