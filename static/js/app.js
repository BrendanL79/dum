// Global state
let socket;
let isDaemonRunning = false;

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
        loadState();
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
    
    if (data.updates && data.updates.length > 0) {
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

// Load configuration
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        dom.configJson.value = JSON.stringify(config, null, 2);
    } catch (error) {
        addLog('Failed to load config: ' + error, 'error');
    }
}

// Save configuration
async function saveConfig() {
    try {
        const configText = dom.configJson.value;
        const config = JSON.parse(configText);

        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (response.ok) {
            addLog('Configuration saved successfully', 'info');
            loadStatus();
        } else {
            const error = await response.json();
            addLog('Failed to save config: ' + error.error, 'error');
        }
    } catch (error) {
        addLog('Invalid JSON: ' + error, 'error');
    }
}

// Load current state
async function loadState() {
    try {
        const response = await fetch('/api/state');
        const state = await response.json();
        dom.stateView.textContent = JSON.stringify(state, null, 2);
    } catch (error) {
        addLog('Failed to load state: ' + error, 'error');
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

        if (data.updates && data.updates.length > 0) {
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
    dom.configJson = document.getElementById('config-json');
    dom.stateView = document.getElementById('state-view');
    dom.historyList = document.getElementById('history-list');
    dom.daemonInterval = document.getElementById('daemon-interval');

    initSocket();

    // Event listeners
    dom.checkNow.addEventListener('click', checkNow);
    dom.toggleDaemon.addEventListener('click', toggleDaemon);
    document.getElementById('refresh-config').addEventListener('click', loadConfig);
    document.getElementById('save-config').addEventListener('click', saveConfig);

    // Tab switching
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    addLog('Web UI initialized', 'info');
});