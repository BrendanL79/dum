#!/usr/bin/env bash
set -euo pipefail

echo "=== ium Test Environment Setup ==="

# Create test state directory
mkdir -p state/test

# Build the web UI image
echo "Building ium web UI image..."
docker compose -f docker-compose.test.yml build ium-test

# Pull old images for test targets
echo "Pulling test target images..."
docker compose -f docker-compose.test.yml pull test-nginx test-redis test-alpine

# Start everything
echo "Starting test environment..."
docker compose -f docker-compose.test.yml up -d

echo ""
echo "Test environment is running:"
echo "  ium Web UI: http://localhost:5051"
echo "  Mode: DRY_RUN=true (check-only, no updates applied)"
echo ""
echo "Test scenarios:"
echo "  1. Open http://localhost:5051 and click 'Check Now'"
echo "  2. Verify updates are detected for all test images"
echo "  3. Toggle auto_update on individual images via config"
echo "  4. Restart with DRY_RUN=false to test real upgrades:"
echo "     docker compose -f docker-compose.test.yml up -d -e DRY_RUN=false ium-test"
echo ""
echo "Teardown: docker compose -f docker-compose.test.yml down -v"
