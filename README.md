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
