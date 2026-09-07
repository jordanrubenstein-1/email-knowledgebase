# AI Feedback Scheduled Task Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically process new AI feedback comments into Asana tasks every 10 minutes, eliminating the need to run `process_ai_feedback.py` manually.

**Architecture:** The webhook server already captures "AI feedback:" comments into `data/ai_feedback_log.yaml`. The existing `process_ai_feedback.py` script evaluates them via Claude and posts to the AI Build Feedback Asana project. We just need it to run on a schedule. Two backlogged entries (from 2026-03-17/18) need immediate processing.

**Tech Stack:** Python (uv), `mcp__scheduled-tasks__create_scheduled_task`

---

### Task 1: Flush the backlog — run the script now

**Files:** No file changes. Just run the existing script.

**Step 1: Run `process_ai_feedback.py` to process the 2 unprocessed entries**

```bash
cd /Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase
uv run python scripts/process_ai_feedback.py
```

Expected output:
- Backfill scan finds 0 new entries (webhook already captured them)
- Evaluates 2 unprocessed entries
- Creates 2 tasks in AI Build Feedback Asana project
- Logs show `✓ Created Asana task <gid>` for each

**Step 2: Verify entries are now `posted_to_asana` in the log**

```bash
grep "status:" data/ai_feedback_log.yaml
```

Expected: both entries show `status: posted_to_asana`

---

### Task 2: Create a scheduled task to run every 10 minutes

**Files:** No file changes. Use the `mcp__scheduled-tasks__create_scheduled_task` tool.

**Step 1: Create the scheduled task**

Use the MCP tool with:
- Command: `cd /Users/jordan.rubenstein/Downloads/email-knowledgebase/email-knowledgebase && uv run python scripts/process_ai_feedback.py --no-backfill`
- Schedule: every 10 minutes
- Description: "Process AI feedback comments from Asana into AI Build Feedback board"

Note: `--no-backfill` skips the slow Asana poll (webhook already captures new entries in real-time). Backfill only needed if ngrok was down.

**Step 2: Verify the scheduled task was created**

Use `mcp__scheduled-tasks__list_scheduled_tasks` to confirm it appears in the list.
