// Global state
let socket;
let isDaemonRunning = false;
let imageConfigs = [];  // Array of image config objects

// Cached DOM elements (initialized in DOMContentLoaded)
const dom = {};

// Initialize Socket.IO connection
function initSocket() {
    socket = io();
    
    socket.on('connect', () => {
        console.log('Connected to server');
        updateConnectionStatus(true);
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        updateConnectionStatus(false);
    });
    
    socket.on('status_update', (data) => {
        updateStatus(data);
    });
    
    socket.on('check_complete', (data) => {
        handleCheckComplete(data);
    });

    socket.on('check_error', (data) => {
        addLog('Check failed: ' + data.error, 'error');
    });

    socket.on('connected', (data) => {
        addLog('Connected: ' + data.status, 'info');
    });
}

// Update connection status indicator
function updateConnectionStatus(connected) {
    if (connected) {
        dom.statusIndicator.classList.add('connected');
        dom.statusText.textContent = 'Connected';
        loadStatus();
    } else {
        dom.statusIndicator.classList.remove('connected');
        dom.statusIndicator.classList.remove('checking');
        dom.statusText.textContent = 'Disconnected';
    }
}

// Update status from server
function updateStatus(data) {
    if (data.checking) {
        dom.statusIndicator.classList.add('checking');
        dom.statusText.textContent = 'Checking...';
        dom.checkNow.disabled = true;
    } else {
        dom.statusIndicator.classList.remove('checking');
        dom.statusText.textContent = 'Connected';
        dom.checkNow.disabled = false;
    }

    if (data.daemon_running !== undefined) {
        isDaemonRunning = data.daemon_running;
        updateDaemonButton();
    }

    if (data.last_check) {
        updateLastCheck(data.last_check);
    }
}

// Load current status
async function loadStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        // Update mode indicator
        if (data.dry_run) {
            dom.modeIndicator.textContent = 'DRY RUN MODE';
            dom.modeIndicator.className = 'mode dry-run';
        } else {
            dom.modeIndicator.textContent = 'PRODUCTION MODE';
            dom.modeIndicator.className = 'mode production';
        }

        isDaemonRunning = data.daemon_running;
        updateDaemonButton();

        if (data.last_check) {
            updateLastCheck(data.last_check);
        }

        // Load other data
        loadConfig();
        loadHistory();
        loadUpdates();

    } catch (error) {
        addLog('Failed to load status: ' + error, 'error');
    }
}

// Update last check time
function updateLastCheck(timestamp) {
    const date = new Date(timestamp);
    dom.lastCheck.textContent = 'Last check: ' + date.toLocaleString();
}

// Update daemon button state
function updateDaemonButton() {
    if (isDaemonRunning) {
        dom.toggleDaemon.textContent = 'Stop Daemon';
        dom.toggleDaemon.classList.add('btn-danger');
        dom.toggleDaemon.classList.remove('btn-secondary');
        dom.daemonIndicator.classList.add('connected');
        dom.daemonStatusText.textContent = 'Daemon: Running';
    } else {
        dom.toggleDaemon.textContent = 'Start Daemon';
        dom.toggleDaemon.classList.remove('btn-danger');
        dom.toggleDaemon.classList.add('btn-secondary');
        dom.daemonIndicator.classList.remove('connected');
        dom.daemonStatusText.textContent = 'Daemon: Stopped';
    }
}

// Handle check complete event
function handleCheckComplete(data) {
    addLog('Check complete', 'info');
    updateLastCheck(data.timestamp);
    
    if (data.updates?.length > 0) {
        displayUpdates(data.updates);
        addLog(`Found ${data.updates.length} updates`, 'warning');
    } else {
        displayNoUpdates();
        addLog('No updates found', 'info');
    }
    
    loadHistory();
}

// Display available updates
function displayUpdates(updates) {
    dom.updateList.innerHTML = '';

    updates.forEach(update => {
        const item = document.createElement('div');
        item.className = 'update-item';
        item.innerHTML = `
            <h3>${update.image}</h3>
            <div class="update-details">
                <span>Base tag: <strong>${update.base_tag}</strong></span>
                <span class="tag-change">${update.old_tag} → ${update.new_tag}</span>
                <span>Digest: ${update.digest.substring(0, 12)}...</span>
            </div>
        `;
        dom.updateList.appendChild(item);
    });
}

// Display no updates message
function displayNoUpdates() {
    dom.updateList.innerHTML = '<p class="no-updates">All images are up to date!</p>';
}

// Load configuration and render cards
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        imageConfigs = config.images || [];
        renderImageCards();
    } catch (error) {
        addLog('Failed to load config: ' + error, 'error');
    }
}

// Render all image cards
function renderImageCards() {
    dom.imageCards.innerHTML = '';
    imageConfigs.forEach((config, index) => {
        const card = createImageCard(config, index);
        dom.imageCards.appendChild(card);
    });
}

// Create a single image card
function createImageCard(config, index, isNew = false) {
    const card = document.createElement('div');
    card.className = 'image-card' + (isNew ? ' is-new' : '');
    card.dataset.index = index;

    // Build badges HTML
    let badges = '';
    if (config.auto_update) {
        badges += '<span class="badge badge-auto-update">Auto-update</span>';
    }
    if (config.base_tag && config.base_tag !== 'latest') {
        badges += `<span class="badge badge-base-tag">${escapeHtml(config.base_tag)}</span>`;
    }

    card.innerHTML = `
        <div class="card-header">
            <div class="card-title">
                <span class="card-image-name">${escapeHtml(config.image || 'New Image')}</span>
                <span class="card-status-badges">${badges}</span>
            </div>
            <div class="card-actions">
                <button class="btn-icon btn-expand" title="Expand/Collapse">
                    <span class="expand-icon">&#9660;</span>
                </button>
                <button class="btn-icon btn-delete" title="Delete Image">&#10005;</button>
            </div>
        </div>
        <div class="card-body">
            <div class="form-group">
                <label>Registry</label>
                <input type="text" class="form-input" name="registry"
                       value="${escapeHtml(config.registry || '')}"
                       placeholder="Docker Hub (default), ghcr.io, gcr.io, etc.">
            </div>

            <div class="form-group">
                <label>Image Name <span class="required">*</span></label>
                <input type="text" class="form-input" name="image"
                       value="${escapeHtml(config.image || '')}"
                       placeholder="e.g., linuxserver/calibre">
                <div class="field-error"></div>
            </div>

            <div class="form-group">
                <label>Regex Pattern <span class="required">*</span></label>
                <input type="text" class="form-input" name="regex"
                       value="${escapeHtml(config.regex || '')}"
                       placeholder="e.g., ^v[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$">
                <div class="regex-validation">
                    <span class="regex-status"></span>
                </div>
                <div class="field-error"></div>
            </div>

            <div class="form-group">
                <label>Test Tag</label>
                <input type="text" class="form-input regex-test-input"
                       placeholder="e.g., v8.11.1-ls358">
                <div class="regex-test-hint">Enter a tag to test if it matches the regex pattern</div>
            </div>

            <div class="form-group">
                <label>Base Tag</label>
                <input type="text" class="form-input" name="base_tag"
                       value="${escapeHtml(config.base_tag || '')}"
                       placeholder="latest (default)">
            </div>

            <div class="form-group">
                <label>Container Name</label>
                <input type="text" class="form-input" name="container_name"
                       value="${escapeHtml(config.container_name || '')}"
                       placeholder="e.g., calibre">
            </div>

            <div class="form-row checkbox-row">
                <label class="checkbox-label">
                    <input type="checkbox" name="auto_update" ${config.auto_update ? 'checked' : ''}>
                    <span>Auto-update enabled</span>
                </label>
                <label class="checkbox-label">
                    <input type="checkbox" name="cleanup_old_images" ${config.cleanup_old_images ? 'checked' : ''}>
                    <span>Cleanup old images</span>
                </label>
            </div>

            <div class="form-group keep-versions-group">
                <label>Keep Versions</label>
                <input type="number" class="form-input form-input-small" name="keep_versions"
                       value="${config.keep_versions || 3}"
                       min="1" max="99">
                <span class="field-hint">Number of image versions to keep when cleanup is enabled</span>
            </div>
        </div>
    `;

    // Attach event listeners
    attachCardEventListeners(card, index);

    // Validate regex on initial load
    const regexInput = card.querySelector('input[name="regex"]');
    if (regexInput.value) {
        validateRegex(regexInput);
    }

    // If new card, expand it
    if (isNew) {
        card.querySelector('.card-header').classList.add('expanded');
        card.querySelector('.card-body').classList.add('expanded');
    }

    return card;
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Attach event listeners to a card
function attachCardEventListeners(card, index) {
    const header = card.querySelector('.card-header');
    const deleteBtn = card.querySelector('.btn-delete');
    const imageInput = card.querySelector('input[name="image"]');
    const regexInput = card.querySelector('input[name="regex"]');
    const testInput = card.querySelector('.regex-test-input');
    const autoUpdateCheckbox = card.querySelector('input[name="auto_update"]');
    const baseTagInput = card.querySelector('input[name="base_tag"]');

    // Toggle expand/collapse
    header.addEventListener('click', (e) => {
        if (e.target.closest('.btn-delete')) return;
        toggleCardExpand(card);
    });

    // Delete button
    deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        showDeleteConfirmation(index);
    });

    // Update card title when image name changes
    imageInput.addEventListener('input', () => {
        const nameSpan = card.querySelector('.card-image-name');
        nameSpan.textContent = imageInput.value || 'New Image';
    });

    // Validate regex pattern
    regexInput.addEventListener('input', () => {
        validateRegex(regexInput);
        updateRegexTest(card);
    });

    // Test regex against input
    testInput.addEventListener('input', () => {
        updateRegexTest(card);
    });

    // Update badges when auto_update or base_tag changes
    autoUpdateCheckbox.addEventListener('change', () => {
        updateCardBadges(card);
    });
    baseTagInput.addEventListener('input', () => {
        updateCardBadges(card);
    });
}

// Toggle card expand/collapse state
function toggleCardExpand(card) {
    const header = card.querySelector('.card-header');
    const body = card.querySelector('.card-body');
    const isExpanded = header.classList.contains('expanded');

    if (isExpanded) {
        header.classList.remove('expanded');
        body.classList.remove('expanded');
    } else {
        header.classList.add('expanded');
        body.classList.add('expanded');
    }
}

// Validate regex pattern
function validateRegex(regexInput) {
    const card = regexInput.closest('.image-card');
    const statusSpan = card.querySelector('.regex-status');

    if (!regexInput.value) {
        statusSpan.className = 'regex-status';
        statusSpan.textContent = '';
        regexInput.classList.remove('invalid', 'valid');
        return true;
    }

    try {
        new RegExp(regexInput.value);
        statusSpan.className = 'regex-status valid';
        statusSpan.textContent = 'Valid regex pattern';
        regexInput.classList.remove('invalid');
        regexInput.classList.add('valid');
        return true;
    } catch (e) {
        statusSpan.className = 'regex-status invalid';
        statusSpan.textContent = 'Invalid regex pattern: ' + e.message;
        regexInput.classList.remove('valid');
        regexInput.classList.add('invalid');
        return false;
    }
}

// Update regex test result
function updateRegexTest(card) {
    const regexInput = card.querySelector('input[name="regex"]');
    const testInput = card.querySelector('.regex-test-input');
    const hintDiv = card.querySelector('.regex-test-hint');

    // Reset to default hint if no test input
    if (!testInput.value) {
        hintDiv.className = 'regex-test-hint';
        hintDiv.textContent = 'Enter a tag to test if it matches the regex pattern';
        return;
    }

    // Show error if test input but no meaningful regex pattern
    const pattern = regexInput.value.trim();
    if (!pattern || pattern === '^') {
        hintDiv.className = 'regex-test-hint no-match';
        hintDiv.textContent = 'Enter a regex pattern first';
        return;
    }

    try {
        const regex = new RegExp(pattern);
        if (regex.test(testInput.value)) {
            hintDiv.className = 'regex-test-hint match';
            hintDiv.textContent = `"${testInput.value}" matches the pattern`;
        } else {
            hintDiv.className = 'regex-test-hint no-match';
            hintDiv.textContent = `"${testInput.value}" does not match the pattern`;
        }
    } catch (e) {
        hintDiv.className = 'regex-test-hint';
        hintDiv.textContent = 'Enter a tag to test if it matches the regex pattern';
    }
}

// Update card badges based on current values
function updateCardBadges(card) {
    const badgesSpan = card.querySelector('.card-status-badges');
    const autoUpdate = card.querySelector('input[name="auto_update"]').checked;
    const baseTag = card.querySelector('input[name="base_tag"]').value;

    let badges = '';
    if (autoUpdate) {
        badges += '<span class="badge badge-auto-update">Auto-update</span>';
    }
    if (baseTag && baseTag !== 'latest') {
        badges += `<span class="badge badge-base-tag">${escapeHtml(baseTag)}</span>`;
    }
    badgesSpan.innerHTML = badges;
}

// Add new image
function addNewImage() {
    const newConfig = {
        image: '',
        regex: '',
        base_tag: '',
        auto_update: false,
        container_name: '',
        cleanup_old_images: false,
        keep_versions: 3,
        registry: ''
    };

    imageConfigs.push(newConfig);
    const card = createImageCard(newConfig, imageConfigs.length - 1, true);
    dom.imageCards.appendChild(card);

    // Scroll to new card and focus image input
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => {
        card.querySelector('input[name="image"]').focus();
    }, 100);
}

// Show delete confirmation modal
function showDeleteConfirmation(index) {
    const imageName = imageConfigs[index]?.image || 'this image';

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-title">Delete Image Configuration</div>
            <div class="modal-body">
                Are you sure you want to delete the configuration for <strong>${escapeHtml(imageName)}</strong>?
                This action cannot be undone until you save.
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary modal-cancel">Cancel</button>
                <button class="btn btn-danger modal-confirm">Delete</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    overlay.querySelector('.modal-cancel').addEventListener('click', () => {
        overlay.remove();
    });

    overlay.querySelector('.modal-confirm').addEventListener('click', () => {
        deleteImage(index);
        overlay.remove();
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.remove();
        }
    });
}

// Delete image from list
function deleteImage(index) {
    imageConfigs.splice(index, 1);
    renderImageCards();
    addLog('Image removed (save to apply changes)', 'warning');
}

// Collect form data from all cards
function collectFormData() {
    const configs = [];
    const cards = dom.imageCards.querySelectorAll('.image-card');
    let hasErrors = false;

    cards.forEach((card) => {
        const imageInput = card.querySelector('input[name="image"]');
        const regexInput = card.querySelector('input[name="regex"]');

        // Clear previous errors
        card.querySelectorAll('.field-error').forEach(el => el.textContent = '');
        card.classList.remove('has-error');

        // Validate required fields
        let cardHasError = false;

        if (!imageInput.value.trim()) {
            imageInput.nextElementSibling.textContent = 'Image name is required';
            imageInput.classList.add('invalid');
            cardHasError = true;
        } else {
            imageInput.classList.remove('invalid');
        }

        if (!regexInput.value.trim()) {
            const errorDiv = regexInput.closest('.form-group').querySelector('.field-error');
            errorDiv.textContent = 'Regex pattern is required';
            regexInput.classList.add('invalid');
            cardHasError = true;
        } else if (!validateRegex(regexInput)) {
            const errorDiv = regexInput.closest('.form-group').querySelector('.field-error');
            errorDiv.textContent = 'Invalid regex pattern';
            cardHasError = true;
        }

        if (cardHasError) {
            card.classList.add('has-error');
            // Expand card to show errors
            card.querySelector('.card-header').classList.add('expanded');
            card.querySelector('.card-body').classList.add('expanded');
            hasErrors = true;
        }

        // Build config object
        const config = {
            image: imageInput.value.trim(),
            regex: regexInput.value.trim()
        };

        // Add optional fields only if they have values
        const baseTag = card.querySelector('input[name="base_tag"]').value.trim();
        const containerName = card.querySelector('input[name="container_name"]').value.trim();
        const registry = card.querySelector('input[name="registry"]').value.trim();
        const autoUpdate = card.querySelector('input[name="auto_update"]').checked;
        const cleanup = card.querySelector('input[name="cleanup_old_images"]').checked;
        const keepVersions = parseInt(card.querySelector('input[name="keep_versions"]').value, 10) || 3;

        if (baseTag) config.base_tag = baseTag;
        if (containerName) config.container_name = containerName;
        if (registry) config.registry = registry;
        if (autoUpdate) config.auto_update = true;
        if (cleanup) config.cleanup_old_images = true;
        if (keepVersions !== 3) config.keep_versions = keepVersions;

        configs.push(config);
    });

    return hasErrors ? null : configs;
}

// Save configuration
async function saveConfig() {
    const configs = collectFormData();

    if (!configs) {
        addLog('Please fix validation errors before saving', 'error');
        return;
    }

    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ images: configs })
        });

        if (response.ok) {
            addLog('Configuration saved successfully', 'info');
            imageConfigs = configs;

            // Remove "is-new" class from all cards
            dom.imageCards.querySelectorAll('.image-card.is-new').forEach(card => {
                card.classList.remove('is-new');
            });

            loadStatus();
        } else {
            const error = await response.json();
            addLog('Failed to save config: ' + error.error, 'error');
        }
    } catch (error) {
        addLog('Error saving configuration: ' + error, 'error');
    }
}

// Load update history
async function loadHistory() {
    try {
        const response = await fetch('/api/history');
        const history = await response.json();

        if (history.length === 0) {
            dom.historyList.innerHTML = '<p class="no-updates">No update history yet.</p>';
            return;
        }

        dom.historyList.innerHTML = '';
        history.reverse().forEach(item => {
            const elem = document.createElement('div');
            elem.className = 'history-item';
            const date = new Date(item.timestamp);
            elem.innerHTML = `
                <span class="history-time">${date.toLocaleString()}</span>
                <span>${item.image}</span>
                <span class="tag-change">${item.old_tag} → ${item.new_tag}</span>
                <span>${item.applied ? '✅ Applied' : '⚠️ Dry run'}</span>
            `;
            dom.historyList.appendChild(elem);
        });
    } catch (error) {
        addLog('Failed to load history: ' + error, 'error');
    }
}

// Load last updates
async function loadUpdates() {
    try {
        const response = await fetch('/api/updates');
        const data = await response.json();

        if (data.updates?.length > 0) {
            displayUpdates(data.updates);
        } else if (data.last_check) {
            // Check was performed but no updates found
            displayNoUpdates();
        } else {
            // No check has been performed yet
            dom.updateList.innerHTML =
                '<p class="no-updates">No check performed yet. Click "Check Now" to scan for updates.</p>';
        }
    } catch (error) {
        addLog('Failed to load updates: ' + error, 'error');
    }
}

// Trigger manual check
async function checkNow() {
    try {
        addLog('Starting manual check...', 'info');
        const response = await fetch('/api/check', { method: 'POST' });
        
        if (!response.ok) {
            const error = await response.json();
            addLog('Check failed: ' + error.error, 'error');
        }
    } catch (error) {
        addLog('Failed to start check: ' + error, 'error');
    }
}

// Toggle daemon mode
async function toggleDaemon() {
    try {
        const action = isDaemonRunning ? 'stop' : 'start';
        const interval = dom.daemonInterval.value;

        const response = await fetch('/api/daemon', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, interval: parseInt(interval) })
        });

        if (response.ok) {
            const result = await response.json();
            addLog(`Daemon ${result.status}`, 'info');
            isDaemonRunning = action === 'start';
            updateDaemonButton();
        } else {
            const error = await response.json();
            addLog('Daemon control failed: ' + error.error, 'error');
        }
    } catch (error) {
        addLog('Failed to control daemon: ' + error, 'error');
    }
}

// Add log entry
function addLog(message, level = 'info') {
    const entry = document.createElement('div');
    entry.className = `log-line ${level}`;
    const timestamp = new Date().toLocaleTimeString();
    entry.textContent = `[${timestamp}] ${message}`;
    dom.logOutput.appendChild(entry);
    dom.logOutput.scrollTop = dom.logOutput.scrollHeight;

    // Keep only last 100 lines
    while (dom.logOutput.children.length > 100) {
        dom.logOutput.removeChild(dom.logOutput.firstChild);
    }
}

// Tab switching
function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.tab === tabName) {
            btn.classList.add('active');
        }
    });
    
    // Update tab panes
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.remove('active');
        if (pane.id === tabName) {
            pane.classList.add('active');
        }
    });
}

// Initialize everything when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Cache frequently accessed DOM elements
    dom.statusIndicator = document.getElementById('status-indicator');
    dom.statusText = document.getElementById('status-text');
    dom.checkNow = document.getElementById('check-now');
    dom.updateList = document.getElementById('update-list');
    dom.logOutput = document.getElementById('log-output');
    dom.toggleDaemon = document.getElementById('toggle-daemon');
    dom.daemonIndicator = document.getElementById('daemon-indicator');
    dom.daemonStatusText = document.getElementById('daemon-status-text');
    dom.lastCheck = document.getElementById('last-check');
    dom.modeIndicator = document.getElementById('mode-indicator');
    dom.imageCards = document.getElementById('image-cards');
    dom.addImageBtn = document.getElementById('add-image');
    dom.saveConfigBtn = document.getElementById('save-config');
    dom.historyList = document.getElementById('history-list');
    dom.daemonInterval = document.getElementById('daemon-interval');

    initSocket();

    // Event listeners
    dom.checkNow.addEventListener('click', checkNow);
    dom.toggleDaemon.addEventListener('click', toggleDaemon);
    document.getElementById('refresh-config').addEventListener('click', loadConfig);
    dom.saveConfigBtn.addEventListener('click', saveConfig);
    dom.addImageBtn.addEventListener('click', addNewImage);

    // Tab switching
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    addLog('Web UI initialized', 'info');
});