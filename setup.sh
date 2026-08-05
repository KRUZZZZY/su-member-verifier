#!/usr/bin/env bash
# ================================================================
#  SU Member Verifier — Linux/macOS One-Click Setup
#  Run: bash setup.sh
# ================================================================
set -e

echo
echo "============================================"
echo "  SU Member Verifier — Setup"
echo "============================================"
echo

# Check for Python
if ! command -v python3 &>/dev/null; then
    echo " [ERROR] Python 3 is not installed."
    echo " Install it: sudo apt install python3 python3-venv (Ubuntu/Debian)"
    echo "           or: brew install python3 (macOS)"
    exit 1
fi
echo " [OK] Python found: $(python3 --version)"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo " Creating virtual environment..."
    python3 -m venv .venv
fi
echo " [OK] Virtual environment ready"

# Install dependencies
echo " Installing dependencies..."
.venv/bin/pip install -e . --quiet
echo " [OK] Dependencies installed"

# Install Playwright browser
echo " Installing Chromium browser (one-time download)..."
.venv/bin/playwright install chromium
echo " [OK] Chromium installed"

# Check for .env
if [ ! -f ".env" ]; then
    echo " Creating .env from template..."
    cp .env.example .env
    echo " [NOTE] Edit .env with your Discord token and other settings"
fi

echo
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo
echo " Next steps:"
echo "   1. Edit .env with your Discord bot token, guild ID, and role ID"
echo "   2. Create a Google Form with these fields:"
echo "      - Discord Username (short answer)"
echo "      - Student Email (short answer)"
echo "   3. Run: .venv/bin/su-verify status   (to check config)"
echo "   4. Run: .venv/bin/su-verify scrape   (to get SU member list)"
echo "   5. Run: .venv/bin/su-verify run      (to verify + assign roles)"
echo
echo " For help, read README.md"
