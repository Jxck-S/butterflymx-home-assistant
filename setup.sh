#!/bin/bash

# Configuration
REPO_URL="github.com/Jxck-S/butterflymx-home-assistant.git"
MANIFEST_PATH="custom_components/butterflymx/manifest.json"

echo "ButterflyMX Integration Setup"
echo "-----------------------------"
echo "This script will configure your private ButterflyMX integration."
echo ""

# Ask for PAT
read -sp "Enter your GitHub Personal Access Token: " PAT
echo ""

if [ -z "$PAT" ]; then
    echo "Error: PAT cannot be empty."
    exit 1
fi

# 1. Handle Cloning (if not already in the repo)
if [ ! -f "$MANIFEST_PATH" ]; then
    echo "Integration not found locally. Cloning..."
    git clone "https://$PAT@$REPO_URL" temp_repo
    if [ $? -ne 0 ]; then
        echo "Error: Failed to clone integration repo."
        exit 1
    fi
    cd temp_repo
fi

# 2. Update manifest.json with the PAT
echo "Updating manifest.json with your PAT..."

# Use python for portable string replacement
python3 -c "
import sys
content = open('$MANIFEST_PATH').read()
new_content = content.replace('YOUR_GITHUB_TOKEN', '$PAT')
with open('$MANIFEST_PATH', 'w') as f:
    f.write(new_content)
"

if [ $? -eq 0 ]; then
    echo "Success! manifest.json has been updated."
    echo ""
    echo "If you are using HACS, you can now add this folder/repo to your installation."
else
    echo "Error: Failed to update manifest.json."
    exit 1
fi
