# Auto-pull hook setup

This repo is configured to automatically run `git pull` at the start of every Claude Code session, so you always have the latest rules and briefing standards.

The hook lives in `.claude/settings.json` (already in the repo). Once you pull, it's active — no extra steps.

## To activate

```bash
git pull
```

That's it. The next time you open Claude Code in this folder, it will pull from GitLab automatically before each session.

## To verify it's working

Open a new Claude Code session in the repo. You should briefly see **"Pulling latest rules from GitLab..."** in the status bar, followed by either `Already up to date.` or a summary of what changed.
