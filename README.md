# ButterflyMX Home Assistant Integration
<img src="assets/logo.png" width="300" />

This integration allows you to control your ButterflyMX access points (doors) and view message/call history from Home Assistant.

## Installation

### 1. Configure with Setup Script
Since the client library is a private repository, this integration requires a GitHub Personal Access Token (PAT) for installation.

1. Clone this repository into your Home Assistant's `custom_components/` directory:
   ```bash
   cd config/custom_components
   git clone https://github.com/Jxck-S/butterflymx-home-assistant.git
   cd butterflymx-home-assistant
   ```
2. Run the setup script to configure your PAT:
   ```bash
   ./setup.sh
   ```
3. Enter your GitHub Personal Access Token when prompted. The script will update `manifest.json` with your token so Home Assistant can automatically install the required client library.

## GitHub Personal Access Token (PAT)

Since both the integration and the client library are private, you need a GitHub PAT to allow Home Assistant to download the dependency. We recommend using a **Fine-grained Personal Access Token** for better security.

### How to Create a Fine-grained PAT
1. Go to [GitHub Settings > Developer Settings > Personal access tokens > Fine-grained tokens](https://github.com/settings/tokens?type=beta).
2. Click **Generate new token**.
3. **Name**: Give it a name (e.g., "Home Assistant ButterflyMX").
4. **Repository access**: Select **Only select repositories**.
5. **Select repositories**: Choose both:
   - `butterflymx-home-assistant`
   - `butterflymx-client`
6. **Permissions**: Under **Repository permissions**:
   - Find **Contents** and set it to **Read-only**.
7. Click **Generate token** and copy it immediately.

### 2. Manual Configuration (Optional)
Alternatively, you can manually replace `YOUR_GITHUB_TOKEN` in `custom_components/butterflymx/manifest.json` with your actual PAT.

### 3. Home Assistant Setup
After configuration, restart Home Assistant and add the ButterflyMX integration via the UI.

4.  **Add Integration**:
    *   Go to **Settings > Devices & Services**.
    *   Click **Add Integration**.
    *   Search for "ButterflyMX".
    *   Enter your Email and Password.

## Entities

*   **Locks**: Each accessible Door/Intercom will appear as a Lock entity.
    *   **Unlock**: Pressing unlock will trigger the `open()` command.
*   **Sensors**:
    *   **Last Message**: Shows the body of the most recent message. Attributes include timestamp and source.
    *   **Last Call**: Shows the device and status of the most recent call. Attributes include type and image URL.
