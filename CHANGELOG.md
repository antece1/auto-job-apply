# Changelog

All notable changes to auto-job-apply are listed here.
Versions follow [semantic versioning](https://semver.org): MAJOR.MINOR.PATCH.

## [Unreleased]

(Changes waiting for the next release go here.)

## [1.1.0] - 2026-11-18

### Added

- **Job Tracker** (`tracker/`, optional): a web page that runs on your own computer (http://localhost:8787) and shows every job in one place.
  - Groups: to apply, applied, error and skipped, plus the responses you got after applying.
  - Funnel by role family, and your interviews as a to-do list, a calendar and a table.
  - `tracker.py` is the server and a command-line row tool (`start`, `stop`, `status`, `find`, `list`, `get`, `update`, `add`, `delete`). `--if-version` stops two edits from overwriting each other.
  - Needs only Python 3. Rows are saved in `tracker/tracker-data.json`, with daily backups; both are git-ignored.
  - Only your computer can open it by default; `--lan` opens it to your Wi-Fi.
- `SKILL.md`: when `profile.md` sets "Job Tracker: Yes", the agent adds or updates a tracker row after every application.
- `profile.example.md`: new "Job Tracker" and "Role families" settings.
- README: Job Tracker section with a screenshot (demo data).

## [1.0.1] - 2026-11-18

### Changed

- README: the intro and "Works with" table now lead with Google Chrome and the agent's Chrome extension. Sign in with Google is listed as an optional part of the Chrome row.

## [1.0.0] - 2026-11-18

First public release.

### Added

- `SKILL.md`: applies to jobs in your own Chrome through the agent's Chrome browser extension.
  - Fit check against your own rules (years required, title level, citizenship or clearance, degree, posting age, repeat employers).
  - Runs Simplify Copilot's Autofill first when it's installed, then fills everything it missed.
  - Follows LinkedIn and Handshake job links through **Apply** or **Apply externally** to the employer's form.
  - Optional **Sign in with Google** with the account you choose. Never types passwords or codes.
  - Attaches your resume and checks that it stuck.
  - Submits only when you say "submit" in that request.
  - Logs every attempt to `applications.csv`.
- First-run profile setup: copies `profile.example.md` to `profile.md` and asks for your details.
- "Learned answers": a question the profile doesn't cover is asked once and saved.
- Helper scripts: `scan-form.js`, `fill-form.js` and `check-form.js`, which also handle React-controlled inputs.
- `templates/JD.md` for optional saved posting notes.
- README with an example screenshot (demo data).

[Unreleased]: https://github.com/antece1/auto-job-apply/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/antece1/auto-job-apply/releases/tag/v1.1.0
[1.0.1]: https://github.com/antece1/auto-job-apply/releases/tag/v1.0.1
[1.0.0]: https://github.com/antece1/auto-job-apply/releases/tag/v1.0.0
