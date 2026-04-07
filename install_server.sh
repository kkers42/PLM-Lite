#!/usr/bin/env bash
# PLM Lite — Server Installer (Linux / macOS)
# Run this ONCE on the machine that will host the vault and database.
#
# Usage:
#   chmod +x install_server.sh
#   ./install_server.sh
#
# Re-running is safe — existing DB and plmlite.ini are not overwritten
# unless you confirm.

set -euo pipefail

REPO_URL="https://github.com/kkers42/PLM-Lite.git"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; WHITE='\033[1;37m'; GRAY='\033[0;37m'; NC='\033[0m'

banner() {
    echo -e "${CYAN}"
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║        PLM Lite — Server Installer       ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo -e "${NC}"
}

prompt_default() {
    local msg="$1" default="$2" val
    read -rp "$(echo -e "${WHITE}${msg}${GRAY} [${default}]${NC}: ")" val
    echo "${val:-$default}"
}

prompt_password() {
    local msg="$1" val
    read -rsp "$(echo -e "${WHITE}${msg}${NC}: ")" val
    echo
    echo "$val"
}

check_python() {
    echo -e "${YELLOW}Checking Python...${NC}"
    if ! command -v python3 &>/dev/null; then
        echo -e "${RED}ERROR: python3 not found. Install Python 3.10+${NC}"
        exit 1
    fi
    local ver
    ver=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local major minor
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if (( major < 3 || (major == 3 && minor < 10) )); then
        echo -e "${RED}ERROR: Python 3.10+ required. Found: $ver${NC}"
        exit 1
    fi
    echo -e "${GREEN}  OK — Python $ver${NC}"
}

get_or_clone_repo() {
    local dir="$1"
    if [[ -d "$dir/.git" ]]; then
        echo -e "${YELLOW}Repository found at $dir — pulling latest...${NC}"
        git -C "$dir" pull
    else
        echo -e "${YELLOW}Cloning PLM Lite from GitHub...${NC}"
        git clone "$REPO_URL" "$dir"
    fi
}

install_dependencies() {
    local dir="$1"
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    python3 -m pip install -e "$dir" --quiet
    echo -e "${GREEN}  OK${NC}"
}

init_database() {
    local install_dir="$1" db_path="$2" admin_user="$3" admin_pass="$4"
    echo -e "${YELLOW}Initializing database at $db_path ...${NC}"
    python3 - <<PYEOF
import sys, os
sys.path.insert(0, os.path.join('$install_dir', 'src'))
from plmlite.database import Database
db = Database('$db_path')
existing = db.get_user('$admin_user')
if existing:
    print('  Admin user already exists — skipping user creation.')
else:
    db.create_user('$admin_user', '$admin_pass', 'admin')
    print('  Admin user created.')
print('  Database ready.')
PYEOF
}

write_config() {
    local install_dir="$1" vault_path="$2" db_path="$3" rev_rule="$4"
    local ini_path="$install_dir/plmlite.ini"
    if [[ -f "$ini_path" ]]; then
        local overwrite
        overwrite=$(prompt_default "plmlite.ini already exists. Overwrite? (y/n)" "n")
        if [[ "$overwrite" != "y" ]]; then
            echo -e "${YELLOW}  Keeping existing plmlite.ini${NC}"
            return
        fi
    fi
    cat > "$ini_path" <<EOF
[plmlite]
vault_path        = $vault_path
db_path           = $db_path
assembly_rev_rule = $rev_rule
EOF
    echo -e "${GREEN}  Written: $ini_path${NC}"
}

# ── Main ──────────────────────────────────────────────────────────────────────

banner
check_python

echo -e "${CYAN}── Install Location ──────────────────────────────────────────${NC}"
INSTALL_DIR=$(prompt_default "Where should PLM Lite be installed?" "/opt/plmlite")
INSTALL_DIR="${INSTALL_DIR%/}"

get_or_clone_repo "$INSTALL_DIR"
install_dependencies "$INSTALL_DIR"

echo ""
echo -e "${CYAN}── Vault & Database Paths ────────────────────────────────────${NC}"
echo -e "${GRAY}  The vault stores all CAD files. Put this on a path accessible${NC}"
echo -e "${GRAY}  to all engineer PCs (Samba share, NFS mount, etc.).${NC}"
echo ""

VAULT_PATH=$(prompt_default "Vault path" "/opt/plmlite/vault")
DB_PATH=$(prompt_default "Database path" "$(dirname "$VAULT_PATH")/plmlite.db")
REV_RULE=$(prompt_default "Assembly rev rule (latest_working / latest_released / latest_created)" "latest_working")

echo ""
echo -e "${CYAN}── First Admin User ──────────────────────────────────────────${NC}"
ADMIN_USER=$(prompt_default "Admin username" "admin")
ADMIN_PASS=$(prompt_password "Admin password")
ADMIN_PASS2=$(prompt_password "Confirm password")
if [[ "$ADMIN_PASS" != "$ADMIN_PASS2" ]]; then
    echo -e "${RED}ERROR: Passwords do not match.${NC}"
    exit 1
fi

# Create vault directory
if [[ ! -d "$VAULT_PATH" ]]; then
    echo -e "${YELLOW}Creating vault directory: $VAULT_PATH${NC}"
    mkdir -p "$VAULT_PATH"
    echo -e "${GREEN}  OK${NC}"
else
    echo -e "${GREEN}Vault directory already exists: $VAULT_PATH${NC}"
fi

# Create DB parent if needed
mkdir -p "$(dirname "$DB_PATH")"

write_config "$INSTALL_DIR" "$VAULT_PATH" "$DB_PATH" "$REV_RULE"
init_database "$INSTALL_DIR" "$DB_PATH" "$ADMIN_USER" "$ADMIN_PASS"

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Server install complete!${NC}"
echo ""
echo -e "${WHITE}  Vault:    $VAULT_PATH${NC}"
echo -e "${WHITE}  Database: $DB_PATH${NC}"
echo -e "${WHITE}  Admin:    $ADMIN_USER${NC}"
echo ""
echo -e "${CYAN}  Next: run install_client.ps1 on each engineer's Windows PC.${NC}"
echo -e "${CYAN}  Give them these paths:${NC}"
echo -e "${WHITE}    Vault path: $VAULT_PATH${NC}"
echo -e "${WHITE}    DB path:    $DB_PATH${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
