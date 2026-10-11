# Security and data-loss reports

storage-steward deletes files automatically, so a bug that removes something it promised to keep is
treated as a security issue, not just a bug.

## Reporting

Please report privately through GitHub:
[Report a vulnerability](https://github.com/deaglecodes/storage-steward/security/advisories/new).

Include the output of `steward.py --version`, your OS, which agent ran the sweep, and if you can, the
lines from `~/.cache/storage-steward/removed.log` for the files involved. You'll get a reply within a few
days. Fixes for data-loss issues ship as a patch release with a note in [CHANGELOG.md](CHANGELOG.md).

For anything that can't cause data loss or expose data, a normal
[issue](https://github.com/deaglecodes/storage-steward/issues) is fine.

## Supported versions

Only the latest release gets fixes. `steward.py --version` shows which one you have; re-run
`./install.sh` after `git pull` to update.

## What counts

- A sweep (automatic or approved) deletes something the [Safety](README.md#safety) section or a keep
  entry says it never deletes.
- A hook or the installer changes or exposes a file outside what the docs describe (agent settings,
  credentials, anything outside your home folder).
- Anything that lets the contents of a repository, a config file or a hook payload make the steward
  delete or run something it otherwise wouldn't.
