#!/bin/bash

# Configuration
REPO_URL="github.com/Jxck-S/butterflymx-home-assistant.git"
MANIFEST_PATH="custom_components/butterflymx/manifest.json"

echo "ButterflyMX Integration Setup"
echo "-----------------------------"
echo "This script will configure your private ButterflyMX integration."
echo ""

# Ask for PAT
echo "To clone/update this private integration, you need a Personal Access Token (PAT)."
echo "Recommendation: Use a 'Fine-grained' token with:"
echo " 1. Access to: 'butterflymx-home-assistant' and 'butterflymx-client'"
echo " 2. Permissions: 'Contents' set to 'Read-only'"
echo ""
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

# Use sed for replacement (more likely to be available than python3)
# Note: Using | as delimiter to avoid issues with / in PAT or URL
sed -i "s|YOUR_GITHUB_TOKEN|$PAT|g" "$MANIFEST_PATH"

if [ $? -eq 0 ]; then
    echo "Success! manifest.json has been updated."
    echo ""
    echo "If you are using HACS, you can now add this folder/repo to your installation."
else
    echo "Error: Failed to update manifest.json."
    exit 1
fi
