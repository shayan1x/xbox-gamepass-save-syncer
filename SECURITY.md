# Security policy

gss reads and replaces game save folders, so a bug can cost someone hundreds of hours of progress. Security and data-safety reports are taken seriously, and thank you for taking the time to send one.

## Supported versions

Only the **latest release** gets security fixes. Please check that a problem still happens on the latest release, or on `main`, before reporting it.

| Version | Supported |
|---|---|
| Latest 0.x release | ✅ |
| Older releases | ❌ Please update |

## Reporting a vulnerability

**Please don't open a public issue for security problems.** Report them privately instead:

1. Go to the repository's **Security** tab and click **Report a vulnerability**. You can also use [this link](https://github.com/shayan1x/xbox-gamepass-save-syncer/security/advisories/new) directly.
2. Describe:
   - **what can happen**, for example "a crafted backup ZIP deletes files outside the save folder"
   - **how to reproduce it**, step by step, ideally with a minimal example
   - **the gss version** (`python gss.py --version`), your Windows version and your Python version
   - **anything you suggest** as a fix

**Leave out your personal data.** Replace Xbox account IDs (XUIDs) and your Windows user name with made-up ones, and don't send real save files or backups. If a crafted file is needed to show the problem, build it from made-up data.

### What happens next

- **Acknowledgement** within **7 days**.
- **A first assessment** within **14 days**: whether it's accepted as a vulnerability, how serious it is, and the plan.
- **A fix** in a patch release (for example `0.1.0` → `0.1.1`). For serious issues this comes as soon as possible.
- **Credit:** once it's fixed, a GitHub security advisory describes the problem and credits you, unless you'd rather not be named.

Please give a fix time to ship before disclosing details publicly. **90 days** is the default, sooner if a fix is released earlier.

## Scope

### In scope

Anything that lets gss do something to a user's PC or data that they didn't ask for, for example:

- **Writing, deleting or replacing files outside** the intended save folder or output folder, for example through a crafted backup ZIP, manifest, save index or game list
- **Losing or corrupting saves** in ways the safety backups don't cover: a command that changes saves without making a `..._before_*.zip` first, or a failed rollback
- **Running commands or code** from data gss reads, such as game names, package names or backup contents
- **Leaking personal data**, such as XUIDs or save contents, anywhere the user didn't choose

### Out of scope

- **Xbox, Microsoft or EA services**, including Xbox cloud sync itself, account security, and games' anti-cheat systems. Report those to the company concerned.
- **Game rules:** whether moving progress between accounts is allowed by a particular game or service. That's between the player and the game.
- **Problems that need an attacker who can already change files in your user profile.** Someone with that access can change your saves directly.
- **Ordinary bugs** with no security or data-loss impact. Please [open a normal issue](CONTRIBUTING.md#report-a-bug).

## How gss protects your data

These protections help with assessing a report. A report showing that one of them can be bypassed is always in scope.

- **It works offline.** gss makes no network connections. The only program it starts is Windows PowerShell, to look up the names of installed games. Package names are checked against a strict pattern first.
- **It only writes where it should:**
  - the save folders of the game and account you name
  - the `backups` and `extracted` output folders
  - temporary folders
- **Backups are checked before they're used.** Restoring a backup:
  - checks every file against its SHA-256 checksum
  - rejects file paths that could lead outside the save folder
  - rejects a manifest whose game ID, container ID or account ID isn't in the expected format, because those name the folder being replaced
- **Every change can be undone.** `restore`, `copy` and `reset` back up the saves they replace before touching them, and put them back automatically if anything fails.
- **It refuses rather than guesses.** gss stops when saves are half-synced, a game name is ambiguous, or data doesn't look right.

## Advice for users

- **Only restore backups you made yourself**, or that come from someone you trust. A backup replaces an account's saves, and is checked for format but not for what the saves contain.
- **Backups contain personal data:** your progress, and your Xbox account ID in file names and inside the ZIP. Don't share them publicly.
- **Keep gss up to date** to get security fixes.
