# Turbo global input selection reproduction

Requires Linux, Node 24, npm 11, Git and Python 3. Uses only independent packages `a` and `b` and generated local Git repositories.

From this folder, choose an empty scratch directory:

```sh
python3 reproduce.py --root /path/to/empty/scratch --versions 2.11.5 2.11.11 2.11.11-canary.2
```

Each exact Turbo version is installed under the scratch directory with `npm --userconfig /dev/null`. The helper records the actual version, `turbo info`, complete commands, exits, task hashes, query results and default `--affected` dry-run identities under `evidence/turbo/`.

The five fixtures compare a committed baseline with one changed file at a time:

- `implicit-attributes`: only `.gitattributes` changes. All four hashes change; both affected selectors return no tasks.
- `global-lock`: `package-lock.json` is explicitly global, then receives one harmless trailing newline. All four hashes change; both selectors return no tasks.
- `global-package`: `packages/a/shared.json` is explicitly global. Changing it moves all four hashes; both selectors return only a's two tasks.
- `nonglobal-package`: the same package file is not global. b's hashes stay unchanged and selection stays in a.
- `ordinary-lock`: a valid npm update changes only a's dependency resolution, without making the lockfile global. Only a's hashes change and both selectors remain scoped to a.

Every fixture includes an independent repeated baseline hash read, no-edit selection, ordinary-source and non-lockfile root-global controls. The root-global control moves and selects all four tasks; the ordinary-source control moves and selects a's two tasks. This distinguishes lost global selection from an empty workspace or failed setup.

Observed on 2.11.5, 2.11.11 and 2.11.11-canary.2: configured global inputs and implicit `.gitattributes` affect hashing but can be omitted from affected selection. Expected: these globally invalidating inputs select every task. A normal nonglobal lockfile resolution change should retain package scope.

Public source references at Turborepo commit `4e3bdf1eff825764acff269b8e71760e5e5c9300`:

- [Implicit attribute input](https://github.com/vercel/turborepo/blob/4e3bdf1eff825764acff269b8e71760e5e5c9300/crates/turborepo-task-hash/src/global_hash.rs#L110-L116)
- [Configured global matcher after package classification](https://github.com/vercel/turborepo/blob/4e3bdf1eff825764acff269b8e71760e5e5c9300/crates/turborepo-repository/src/change_mapper/package.rs#L188-L212)

The sibling `snapshots/` folders contain the exact baseline and changed-file source bytes captured from the executed fixtures, including their npm lockfiles. They contain no Git database or installed dependency tree. The helper creates fresh repositories to retain comparable base/head commits.
