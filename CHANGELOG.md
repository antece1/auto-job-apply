# Changelog

All notable changes to auto-job-apply are listed here.
Versions follow [semantic versioning](https://semver.org): MAJOR.MINOR.PATCH.

## [Unreleased]

(Changes waiting for the next release go here.)

## [1.2.0] - 2026-11-25

### Added

- Job Tracker, **Funnel** tab: two charts under the tables. "The funnel" shows how far your applications got (heard back, past the confirmation, contact, interview, offer); "Outcomes by role family" splits each family's applications from the best outcome to the worst, with the contact rate. Hover or focus a bar for its numbers. Colors work in light and dark mode and for color-blind readers.
- Job Tracker, **Interview calendar**: past interviews stay on the calendar. By default they fold into one narrow "Past" column on the left; "Show past" puts them back on their days, shrunk and muted. The choice is remembered per browser. The calendar also includes interviewed, rejected and offer cards whose interview time is known, and its heading counts upcoming and past interviews.
- Job Tracker: interview cards can set `interviewType` (`hr` or `tech`, with an optional `interviewTypeWhy`) to show an **HR** or **Tech** tag on the calendar and in the interview table.
- `tracker.py`: with `--lan`, the page and `status` also show the computer's `<name>.local` address, which keeps working when the router hands out a new IP address.

### Changed

- `tracker.py serve` listens right away. While the data file can't be read yet (`--wait`, for example a synced folder just after sign-in), the page shows a "starting…" message that opens the tracker by itself, instead of the browser's "can't connect". `status` reports "starting" in that state.
- `SKILL.md` fit check: an ITAR/EAR "U.S. person" requirement admits U.S. permanent residents, so it no longer counts as a citizenship requirement on its own.

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

[Unreleased]: https://github.com/antece1/auto-job-apply/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/antece1/auto-job-apply/releases/tag/v1.2.0
[1.1.0]: https://github.com/antece1/auto-job-apply/releases/tag/v1.1.0
[1.0.1]: https://github.com/antece1/auto-job-apply/releases/tag/v1.0.1
[1.0.0]: https://github.com/antece1/auto-job-apply/releases/tag/v1.0.0
