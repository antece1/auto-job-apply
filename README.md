# auto-job-apply

An AI agent skill that fills out job applications for you in your own Chrome.

Give the agent one or more job links. For each one it:

1. Opens the posting and checks it against **your** fit rules (years required, title level, citizenship or clearance, degree, posting age, repeat employers), and skips jobs that don't fit.
2. Runs [Simplify Copilot](https://simplify.jobs/copilot)'s **Autofill**, if you have it installed.
3. Scans the form and fills every remaining field from your `profile.md`, including selects, radio buttons and React-style dropdowns.
4. Attaches the right resume and checks that it stuck.
5. Shows you a table of every answer it entered.
6. Clicks **Submit** only if you said "submit" in that request. Otherwise it stops so you can review.
7. Logs each attempt to `applications.csv`.

It never types passwords, verification codes, Social Security numbers, bank details or ID numbers, and it never solves CAPTCHAs. It hands those back to you.

## Requirements

- An AI agent that supports `SKILL.md` skills (desktop app or CLI)
- The agent's **Chrome browser extension**, installed and signed in. The agent works in your real Chrome, so your job-site logins and extensions are available.
- Optional: **Simplify Copilot** Chrome extension, which speeds up common fields.

## Install

Clone the repo:

```bash
git clone https://github.com/antece1/auto-job-apply
```

Move the `auto-job-apply` folder into your agent's skills folder, then restart the agent so it picks up the skill.

## Set up your profile

Run:

```
/auto-job-apply set up my profile
```

The agent copies `profile.example.md` to `profile.md` and asks for your details a few at a time: contact info, resume path, education, work authorization, standard answers, and fit rules. You can also copy the file and edit it by hand.

`profile.md` is the **only** source the agent uses for facts about you. When a form asks something the profile doesn't cover, the agent asks you once and saves your answer under "Learned answers", so you're never asked again.

## Use it

Fill out an application but stop before submitting:

```
/auto-job-apply https://jobs.lever.co/acme/1234
```

Fill out and submit several applications:

```
/auto-job-apply https://boards.greenhouse.io/acme/jobs/1 https://jobs.ashbyhq.com/beta/2 submit
```

At the end you get a summary table (company, role, status, anything left for you), and every attempt is logged in `applications.csv`.

## Files

| File | What it is |
|---|---|
| `SKILL.md` | The instructions the agent follows |
| `scan-form.js` | Lists every visible form field with its question text and tags it for filling |
| `fill-form.js` | Fills text, textarea and select fields, including React-controlled inputs |
| `check-form.js` | Reads every tagged field back, including the attached file name |
| `profile.example.md` | Template for your `profile.md` |
| `templates/JD.md` | Template for saved posting notes (optional, set a "Postings folder" in your profile) |
| `profile.md`, `applications.csv` | **Your** data, created on first run. Ignored by git, so never committed. |

## Privacy

Your `profile.md`, `applications.csv` and any resume files are listed in `.gitignore`. Running `git pull` to update the skill never touches them. Don't publish them.

## Tips

- Run one applying session at a time. Sessions share Chrome's tab group and can move each other's tabs.
- Workday, iCIMS and some other portals require an account and emailed codes. The agent stops and lets you do those parts.
- If a form shows up blank to the scanner, it's usually inside an iframe. The agent opens the frame directly and continues.

## License

MIT. See [LICENSE](LICENSE).
