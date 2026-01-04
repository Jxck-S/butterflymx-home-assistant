#!/bin/bash

# Configuration
REPO_URL="github.com/Jxck-S/butterflymx-home-assistant.git"
DEST_DIR="custom_components/butterflymx"
CACHE_FILE=".bmx_setup_cache"

echo "======================================"
echo "   ButterflyMX Integration Setup"
echo "======================================"
echo "Current directory: $(pwd)"

# 0. Check/Create custom_components directory
if [ ! -d "custom_components" ]; then
    echo "Creating 'custom_components' directory..."
    mkdir -p custom_components
fi

# 1. Handle PAT (Auto-cache)
PAT=""
if [ -f "$CACHE_FILE" ]; then
    PAT=$(cat "$CACHE_FILE")
    echo "Using cached GitHub token..."
else
    echo "No cached token found."
    read -sp "Enter your GitHub Personal Access Token: " PAT
    echo ""
    if [ -z "$PAT" ]; then
        echo "Error: PAT cannot be empty."
        exit 1
    fi
    echo "$PAT" > "$CACHE_FILE"
    chmod 600 "$CACHE_FILE"
fi

# 2. Determine Mode (Auto-know)
if [ -d "$DEST_DIR" ]; then
    echo "Existing installation found. Performing automatic update..."
    rm -rf "$DEST_DIR"
else
    echo "No existing installation found. Performing new install..."
fi

# 3. Execution
echo "Fetching latest integration files..."
rm -rf butterflymx_temp # Ensure clean start
git clone --quiet "https://$PAT@$REPO_URL" butterflymx_temp

if [ $? -ne 0 ]; then
    echo "Error: Failed to clone repository. Check your PAT or internet connection."
    # If it failed, maybe the PAT in cache is old? Clear it to prompt next time.
    rm -f "$CACHE_FILE"
    exit 1
fi

echo "Installing integration..."
cp -r butterflymx_temp/custom_components/butterflymx custom_components/
rm -rf butterflymx_temp

# 4. Manifest Update (Always update to ensure latest requirements)
if [ -f "$DEST_DIR/manifest.json" ]; then
    echo "Updating manifest.json requirements..."
    
    # Portable sed with backup file for macOS/Linux compatibility
    REQ_URL="git+https://$PAT@github.com/Jxck-S/butterflymx-client.git#egg=butterflymx-client"
    
    # Replace the line containing butterflymx-client.git
    sed -i.bak "s|.*butterflymx-client.git.*|\"        $REQ_URL\"|g" "$DEST_DIR/manifest.json"
    
    # Also replace any lingering placeholders
    sed -i.bak "s|YOUR_GITHUB_TOKEN|$PAT|g" "$DEST_DIR/manifest.json"
    
    # Clean up backup
    rm "$DEST_DIR/manifest.json.bak"
    
    echo "Success! Setup complete."
    echo "Please restart Home Assistant to apply changes."
else
    echo "Error: manifest.json not found in $DEST_DIR"
    exit 1
fi


