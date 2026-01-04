#!/bin/bash

# Configuration
REPO_URL="github.com/Jxck-S/butterflymx-client.git"
DEST_DIR="custom_components/butterflymx/butterflymx"
TEMP_DIR="temp_butterflymx_client"

echo "ButterflyMX Client Bundler"
echo "--------------------------"
echo "This script will clone the private client library and bundle it into the integration folder."
echo ""

# Ask for PAT
read -sp "Enter your GitHub Personal Access Token: " PAT
echo ""

if [ -z "$PAT" ]; then
    echo "Error: PAT cannot be empty."
    exit 1
fi

# Clean up any existing temp dir
rm -rf "$TEMP_DIR"
rm -rf "$DEST_DIR"

# Clone using PAT
echo "Cloning repository..."
git clone "https://$PAT@$REPO_URL" "$TEMP_DIR"

if [ $? -ne 0 ]; then
    echo "Error: Failed to clone repository. Check your PAT and permissions."
    exit 1
fi

# Move the package
echo "Bundling files..."
mkdir -p "$DEST_DIR"
cp -r "$TEMP_DIR/butterflymx/"* "$DEST_DIR/"

# Clean up
rm -rf "$TEMP_DIR"

echo ""
echo "Successfully bundled ButterflyMX client into $DEST_DIR"
echo "You can now push these changes to your integration repository."
