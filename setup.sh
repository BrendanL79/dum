#!/bin/bash

# Image Update Manager Setup Script
# This script helps set up and manage the Image Update Manager

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.json"
STATE_DIR="${SCRIPT_DIR}/state"
PYTHON_SCRIPT="${SCRIPT_DIR}/docker_updater.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

check_dependencies() {
    print_info "Checking dependencies..."
    
    # Check for Docker
    if command -v docker &> /dev/null; then
        print_success "Docker is installed"
    else
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check for Python 3
    if command -v python3 &> /dev/null; then
        print_success "Python 3 is installed"
    else
        print_error "Python 3 is not installed. Please install Python 3."
        exit 1
    fi
    
    # Check for pip
    if python3 -m pip --version &> /dev/null; then
        print_success "pip is installed"
    else
        print_error "pip is not installed. Installing pip..."
        curl https://bootstrap.pypa.io/get-pip.py | python3
    fi
}

install_python_dependencies() {
    print_info "Installing Python dependencies..."
    python3 -m pip install --user requests
    print_success "Python dependencies installed"
}

setup_directories() {
    print_info "Setting up directories..."
    
    # Create state directory
    if [ ! -d "$STATE_DIR" ]; then
        mkdir -p "$STATE_DIR"
        print_success "Created state directory"
    else
        print_success "State directory exists"
    fi
}

create_sample_config() {
    if [ -f "$CONFIG_FILE" ]; then
        print_info "Config file already exists at $CONFIG_FILE"
        read -p "Do you want to overwrite it with a sample config? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            return
        fi
    fi
    
    cat > "$CONFIG_FILE" << 'EOF'
{
  "images": [
    {
      "image": "linuxserver/calibre",
      "base_tag": "latest",
      "regex": "v[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+",
      "auto_update": false,
      "container_name": "calibre"
    }
  ]
}
EOF
    print_success "Created sample config file at $CONFIG_FILE"
    print_info "Edit this file to add your Docker images and regex patterns"
}

test_regex() {
    print_info "Testing regex pattern for an image..."
    read -p "Enter image name (e.g., linuxserver/calibre): " image
    read -p "Enter base tag to track (e.g., latest, stable, 15): " base_tag
    base_tag=${base_tag:-latest}
    read -p "Enter regex pattern (e.g., v[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+): " regex
    
    # Create temporary test config
    cat > /tmp/test_config.json << EOF
{
  "images": [
    {
      "image": "$image",
      "base_tag": "$base_tag",
      "regex": "$regex",
      "auto_update": false
    }
  ]
}
EOF
    
    print_info "Testing pattern..."
    python3 "$PYTHON_SCRIPT" /tmp/test_config.json --state /tmp/test_state.json --check-only
    
    rm -f /tmp/test_config.json /tmp/test_state.json
}

check_updates() {
    if [ ! -f "$CONFIG_FILE" ]; then
        print_error "Config file not found. Run setup first."
        exit 1
    fi
    
    print_info "Checking for updates..."
    python3 "$PYTHON_SCRIPT" "$CONFIG_FILE" --state "$STATE_DIR/image_update_state.json" --check-only
}

run_updates() {
    if [ ! -f "$CONFIG_FILE" ]; then
        print_error "Config file not found. Run setup first."
        exit 1
    fi
    
    print_info "Running updates..."
    python3 "$PYTHON_SCRIPT" "$CONFIG_FILE" --state "$STATE_DIR/image_update_state.json"
}

run_daemon() {
    if [ ! -f "$CONFIG_FILE" ]; then
        print_error "Config file not found. Run setup first."
        exit 1
    fi
    
    read -p "Enter check interval in seconds (default 3600): " interval
    interval=${interval:-3600}
    
    print_info "Starting daemon mode (checking every $interval seconds)..."
    print_info "Press Ctrl+C to stop"
    python3 "$PYTHON_SCRIPT" "$CONFIG_FILE" --state "$STATE_DIR/image_update_state.json" --daemon --interval "$interval"
}

setup_systemd() {
    print_info "Setting up systemd service..."
    
    SERVICE_FILE="/etc/systemd/system/image-updater.service"
    
    sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Image Update Manager
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $PYTHON_SCRIPT $CONFIG_FILE --state $STATE_DIR/image_update_state.json --daemon --interval 3600
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    sudo systemctl daemon-reload
    print_success "Systemd service created"
    
    read -p "Do you want to enable and start the service now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo systemctl enable image-updater.service
        sudo systemctl start image-updater.service
        print_success "Service enabled and started"
        print_info "Check status with: sudo systemctl status image-updater.service"
    fi
}

setup_cron() {
    print_info "Setting up cron job..."
    
    # Check if cron job already exists
    if crontab -l 2>/dev/null | grep -q "$PYTHON_SCRIPT"; then
        print_info "Cron job already exists"
        return
    fi
    
    read -p "How often to check? (1=hourly, 2=daily, 3=weekly): " frequency
    
    case $frequency in
        1)
            schedule="0 * * * *"
            desc="hourly"
            ;;
        2)
            schedule="0 2 * * *"
            desc="daily at 2 AM"
            ;;
        3)
            schedule="0 2 * * 0"
            desc="weekly on Sunday at 2 AM"
            ;;
        *)
            print_error "Invalid selection"
            return
            ;;
    esac
    
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$schedule /usr/bin/python3 $PYTHON_SCRIPT $CONFIG_FILE --state $STATE_DIR/image_update_state.json") | crontab -
    
    print_success "Cron job added ($desc)"
    print_info "View cron jobs with: crontab -l"
}

show_menu() {
    echo
    echo "Image Update Manager Menu"
    echo "==============================="
    echo "1. Initial setup"
    echo "2. Edit configuration"
    echo "3. Test regex pattern"
    echo "4. Check for updates (no changes)"
    echo "5. Run updates once"
    echo "6. Run in daemon mode"
    echo "7. Setup systemd service"
    echo "8. Setup cron job"
    echo "9. View current state"
    echo "0. Exit"
    echo
}

view_state() {
    if [ -f "$STATE_DIR/image_update_state.json" ]; then
        print_info "Current state:"
        python3 -m json.tool "$STATE_DIR/image_update_state.json"
    else
        print_info "No state file found. Run an update check first."
    fi
}

# Main menu loop
main() {
    print_info "Image Update Manager Setup"
    
    while true; do
        show_menu
        read -p "Enter your choice: " choice
        
        case $choice in
            1)
                check_dependencies
                install_python_dependencies
                setup_directories
                create_sample_config
                ;;
            2)
                ${EDITOR:-nano} "$CONFIG_FILE"
                ;;
            3)
                test_regex
                ;;
            4)
                check_updates
                ;;
            5)
                run_updates
                ;;
            6)
                run_daemon
                ;;
            7)
                setup_systemd
                ;;
            8)
                setup_cron
                ;;
            9)
                view_state
                ;;
            0)
                print_info "Goodbye!"
                exit 0
                ;;
            *)
                print_error "Invalid choice"
                ;;
        esac
    done
}

# Run main function
main

