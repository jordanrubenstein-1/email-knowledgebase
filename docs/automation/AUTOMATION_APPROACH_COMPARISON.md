# Braze Campaign Automation: Approach Comparison

## The Core Problem

Braze REST API **does not support creating campaigns programmatically**. We need a workaround that balances:
- ✅ Full automation
- ✅ Campaign tracking & analytics
- ✅ Easy campaign management in Braze UI
- ✅ Historical record of what was sent

## Approach Comparison

### Approach 1: Single API-Triggered Campaign Shell

**How it works:**
- Create ONE API-triggered campaign in Braze UI
- Trigger it multiple times via API with different content/audiences
- All sends appear under the same campaign ID

**Pros:**
- ✅ Fully automated after initial setup
- ✅ Fast to implement
- ✅ No manual steps per campaign
- ✅ Can reuse same campaign structure

**Cons:**
- ❌ **All sends grouped under one campaign ID** - can't distinguish individual campaigns
- ❌ **Analytics are aggregated** - can't see performance of specific sends
- ❌ **Hard to track what was sent when** - all triggers look the same in Braze
- ❌ **No campaign-level metadata** - subject lines, dates, etc. not easily visible
- ❌ **Difficult to archive/disable** - can't archive individual campaigns
- ❌ **Reporting challenges** - can't generate reports for specific campaigns
- ❌ **Knowledgebase integration** - harder to match sends to campaign records

**Use case:** Good for transactional/event-based sends where you don't need individual campaign tracking

---

### Approach 2: Templates API + Manual Campaign Creation

**How it works:**
- Create email templates programmatically via API
- Create campaigns manually in Braze UI (but templates are ready)
- Schedule/send via API once campaign exists

**Pros:**
- ✅ **Each campaign is separate** - full tracking & analytics per campaign
- ✅ **Easy to see what sent when** - clear campaign history in Braze
- ✅ **Individual performance metrics** - open rates, click rates per campaign
- ✅ **Campaign metadata visible** - names, dates, subjects in Braze UI
- ✅ **Easy to archive/disable** - can manage campaigns individually
- ✅ **Knowledgebase integration** - can match campaigns to records easily
- ✅ **Templates are automated** - content creation is fully automated

**Cons:**
- ⚠️ **Requires manual campaign creation** - 2-3 minutes per campaign in UI
- ⚠️ **Not 100% automated** - still need to click through Braze UI

**Use case:** Best for marketing campaigns where individual tracking matters

---

### Approach 3: Content Blocks + Manual Campaign Creation

**How it works:**
- Create content blocks programmatically via API
- Create campaigns manually in Braze UI
- Reference content blocks in campaign
- Schedule/send via API

**Pros:**
- ✅ Similar to Approach 2
- ✅ Content blocks can be reused across campaigns
- ✅ Can update content blocks programmatically

**Cons:**
- ⚠️ Same manual step as Approach 2
- ⚠️ Content blocks are less flexible than templates (no subject/preheader)

**Use case:** When you need reusable content components

---

### Approach 4: Hybrid - Templates + Scripted Campaign Creation (Browser Automation)

**How it works:**
- Create email templates programmatically via API
- Use browser automation (Selenium/Playwright) to automate campaign creation in Braze UI
- Script navigates Braze dashboard, fills forms, selects templates/audiences
- Schedule/send via API once campaign exists

**Pros:**
- ✅ **Fully automated** - no manual steps required
- ✅ **Each campaign is separate** - full tracking & analytics per campaign
- ✅ **Individual performance metrics** - open rates, click rates per campaign
- ✅ **Campaign metadata visible** - names, dates, subjects in Braze UI
- ✅ **Templates are automated** - content creation is fully automated
- ✅ **Knowledgebase integration** - can match campaigns to records easily

**Cons:**
- ⚠️ **Browser automation is fragile** - UI changes break scripts
- ⚠️ **Requires maintenance** - need to update selectors when Braze updates UI
- ⚠️ **Slower than API** - browser automation is slower than direct API calls
- ⚠️ **Authentication complexity** - need to handle Braze login/session management
- ⚠️ **Error handling** - harder to debug when automation fails
- ⚠️ **Resource intensive** - requires browser instance running

**Implementation Steps:**
1. Create email template via API:
   ```python
   template_id = create_email_template(campaign_config, brand)
   ```
2. Use browser automation to create campaign:
   ```python
   from selenium import webdriver
   # or
   from playwright.sync_api import sync_playwright
   
   # Navigate to Braze, login, create campaign
   # Select template, set subject, preheader, audience
   # Save campaign
   ```
3. Schedule/send via API once campaign ID is obtained

**Tools:**
- **Selenium** - Most common, mature ecosystem
- **Playwright** - Modern, faster, better error handling
- **Puppeteer** - Node.js based (would need Python wrapper)

**Use case:** Good for full automation when you're willing to maintain browser automation scripts and handle UI changes

---

## Final Recommendation

**For your use case (marketing campaigns with performance tracking needs):**

👉 **Use Approach 2: Templates API + Manual Campaign Creation**

**Why:**
- Individual campaign tracking is important for marketing analysis
- The 2-3 minute manual step is acceptable trade-off
- You get full Braze analytics and reporting
- Knowledgebase integration works perfectly
- Future-proof and maintainable

**The automation still saves significant time:**
- Template/content creation: Automated ✅
- Campaign scheduling: Automated ✅
- Only campaign creation: Manual (2-3 min) ⚠️

This gives you **80% automation with 100% tracking capability**.

**Approach 4 Consideration:**
⚠️ **Viable but requires maintenance** - Browser automation can provide full automation, but requires ongoing maintenance when Braze updates their UI. Consider the trade-off between full automation and maintenance burden vs. the 2-3 minute manual step in Approach 2.
