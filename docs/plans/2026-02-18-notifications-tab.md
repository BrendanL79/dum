# Notifications Tab Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the Notifications section out of the Configuration tab and into its own top-level "Notifications" tab, and rename "Configuration" to "Images".

**Architecture:** Pure HTML restructuring + small JS additions. The tab-switching mechanism already handles any new `data-tab` button generically. A new `notifDirty` flag mirrors the existing `configDirty` pattern, with its own banner instance. Both Save buttons call the same `saveConfig()`.

**Tech Stack:** Vanilla JS, HTML, CSS — no build step. No backend changes.

---

### Task 1: Restructure `templates/index.html`

**Files:**
- Modify: `templates/index.html`

**Step 1: Rename "Configuration" tab button label**

In the `.tabs` div (line 37), change the button text from `Configuration` to `Images`.
Keep `data-tab="config"` unchanged.

```html
<button class="tab-button active" data-tab="updates">Updates</button>
<button class="tab-button" data-tab="config">Images</button>
<button class="tab-button" data-tab="notifications">Notifications</button>
<button class="tab-button" data-tab="history">History</button>
<button class="tab-button" data-tab="log">Log <span id="log-badge" class="tab-badge" style="display:none"></span></button>
```

**Step 2: Remove `#notifications-section` from the `#config` pane**

Delete lines 67–120 from `index.html` (the entire `<div id="notifications-section" ...>` block including closing `</div>`). The `#config` pane should end at the closing `</div>` of `#image-cards`.

**Step 3: Add the new `#notifications` tab pane**

Insert a new tab pane after the closing `</div>` of the `#config` pane (before `<div id="history" ...>`):

```html
<div id="notifications" class="tab-pane">
    <div id="unsaved-banner-notifications" class="unsaved-banner" style="display:none">
        You have unsaved changes &mdash;
        <button class="btn btn-sm btn-primary" onclick="saveConfig()">Save Now</button>
    </div>
    <h2>Notifications</h2>
    <div class="config-toolbar">
        <button id="save-notifications-config" class="btn btn-success">Save Notifications</button>
    </div>

    <div class="notification-block">
        <h4>ntfy.sh</h4>
        <div class="form-group">
            <label>Topic URL</label>
            <input type="text" id="ntfy-url" class="form-input"
                   placeholder="https://ntfy.sh/my-topic">
        </div>
        <div class="form-group">
            <label>Priority</label>
            <select id="ntfy-priority" class="form-input">
                <option value="min">min</option>
                <option value="low">low</option>
                <option value="default" selected>default</option>
                <option value="high">high</option>
                <option value="urgent">urgent</option>
            </select>
        </div>
        <div class="notification-actions">
            <button id="test-ntfy" class="btn btn-secondary btn-sm">Test</button>
            <span id="ntfy-test-status" class="detect-status"></span>
        </div>
    </div>

    <div class="notification-block">
        <h4>Webhook</h4>
        <div class="form-group">
            <label>URL</label>
            <input type="text" id="webhook-url" class="form-input"
                   placeholder="https://hooks.example.com/...">
        </div>
        <div class="form-row">
            <div class="form-group">
                <label>Method</label>
                <select id="webhook-method" class="form-input">
                    <option value="POST" selected>POST</option>
                    <option value="PUT">PUT</option>
                </select>
            </div>
        </div>
        <div class="form-group">
            <label>Body Template <span class="field-hint">(optional)</span></label>
            <textarea id="webhook-body-template" class="form-input" rows="3"
                      placeholder='{"content": "Update: $image → $new_version"}'></textarea>
            <span class="field-hint">Variables: $image, $old_version, $new_version, $event, $digest, $auto_update. Leave blank to send the raw JSON payload.</span>
        </div>
        <div class="notification-actions">
            <button id="test-webhook" class="btn btn-secondary btn-sm">Test</button>
            <span id="webhook-test-status" class="detect-status"></span>
        </div>
    </div>
</div>
```

**Step 4: Verify HTML structure manually**

Open the app in a browser. Confirm:
- Tab bar shows: Updates | Images | Notifications | History | Log
- Clicking "Images" shows only image cards (no Notifications section below)
- Clicking "Notifications" shows the ntfy.sh and Webhook blocks

**Step 5: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): move notifications to top-level tab, rename Config to Images"
```

---

### Task 2: Update `static/js/app.js` — dirty tracking and new Save button

**Files:**
- Modify: `static/js/app.js`

**Context:** The existing pattern uses `configDirty` flag + `markConfigDirty()` / `markConfigClean()` targeting `#unsaved-banner` by ID. Notification fields currently have no change listeners at all. We need a parallel `notifDirty` flag for the Notifications tab.

**Step 1: Add `notifDirty` flag near the existing `configDirty` declaration**

Find the line that declares `configDirty` (search for `let configDirty` or `configDirty = false`). Add `notifDirty` on the next line:

```js
let notifDirty = false;
```

**Step 2: Add `markNotifDirty()` and `markNotifClean()` functions**

Immediately after the `markConfigClean()` function, add:

```js
function markNotifDirty() {
    if (notifDirty) return;
    notifDirty = true;
    const banner = document.getElementById('unsaved-banner-notifications');
    if (banner) banner.style.display = '';
}

function markNotifClean() {
    notifDirty = false;
    const banner = document.getElementById('unsaved-banner-notifications');
    if (banner) banner.style.display = 'none';
}
```

**Step 3: Update `markConfigClean()` to also clear the notifications banner**

`saveConfig()` calls `markConfigClean()` on success. Since saving writes both images and notifications to the same file, a successful save should clear both banners.

Find `markConfigClean()` and add a `markNotifClean()` call inside it:

```js
function markConfigClean() {
    configDirty = false;
    const banner = document.getElementById('unsaved-banner');
    if (banner) banner.style.display = 'none';
    markNotifClean();
}
```

**Step 4: Wire notification field change listeners in `init()`**

Find the block in `init()` that registers `dom.ntfyUrl`, `dom.ntfyPriority`, etc. (around line 1317). After those assignments, add change/input listeners:

```js
dom.ntfyUrl.addEventListener('input', markNotifDirty);
dom.ntfyPriority.addEventListener('change', markNotifDirty);
dom.webhookUrl.addEventListener('input', markNotifDirty);
dom.webhookMethod.addEventListener('change', markNotifDirty);
dom.webhookBodyTemplate.addEventListener('input', markNotifDirty);
```

**Step 5: Register the new Save button in `dom` and wire its click listener**

In the `dom` assignment block in `init()`, add:

```js
dom.saveNotifBtn = document.getElementById('save-notifications-config');
```

Then in the event listeners block, add:

```js
dom.saveNotifBtn.addEventListener('click', saveConfig);
```

**Step 6: Verify in browser**

- Edit a notification field → unsaved banner appears in the Notifications pane
- Click "Save Notifications" → banner disappears, toast shows "Configuration saved"
- Edit an image card, then click Save in Images tab → both banners disappear

**Step 7: Commit**

```bash
git add static/js/app.js
git commit -m "feat(ui): add notifications dirty tracking and save button wiring"
```

---

### Task 3: Clean up `static/css/style.css`

**Files:**
- Modify: `static/css/style.css`

**Step 1: Remove layout-glue rules from `.notifications-section`**

Find the `.notifications-section` rule block (around line 843):

```css
.notifications-section {
    margin-top: 30px;
    border-top: 1px solid var(--border);
    padding-top: 20px;
}
```

Delete this entire rule block. The `.notification-block`, `.notification-actions`, and `.notifications-heading` rules are all still valid and should be kept.

**Step 2: Verify visually**

Reload the app. Check the Notifications tab — the blocks should render cleanly without unexpected top margin/border.

**Step 3: Commit**

```bash
git add static/css/style.css
git commit -m "style(ui): remove notifications-section layout glue now that it's a top-level tab"
```
