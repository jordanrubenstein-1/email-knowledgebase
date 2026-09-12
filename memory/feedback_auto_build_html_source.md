---
name: feedback-auto-build-html-source
description: "When auto-building campaigns, never use old HTML files as the source for the email body — always use the Asana brief and designer assets"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 65a379f3-72f1-4519-8456-c487e8b2e19f
---

Never look at previous campaign HTML files as a source or template when auto-building a new campaign.

**Why:** Old HTML files contain last year's images (with expiring CDN URLs), stale links, and outdated content. Using them as a starting point is always wrong and was explicitly called out as an anti-pattern.

**How to apply:** For designed email auto-builds, the HTML body must come from:
1. **The Asana task brief** — the Body Copy section in the description defines the slice structure, links, alt text, and content
2. **The designer's assets** — the Email Slices/Banners/Blocks Details field points to Google Drive (or similar) where the designer provides the actual image files/slice exports

The correct auto-build flow reads the Asana brief to understand structure, fetches assets from Google Drive, and constructs the HTML from those sources — not from any prior campaign's HTML in `campaigns/html/`.
