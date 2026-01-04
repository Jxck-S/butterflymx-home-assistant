# ButterflyMX Home Assistant Integration

This directory contains a custom component for Home Assistant that uses the `butterflymx-client` library.

## Installation

1.  **Copy Folder**: Copy the `home_assistant_integration/custom_components/butterflymx` folder to your Home Assistant's `config/custom_components/` directory.

2.  **Configure Requirement (Important)**:
    Open `custom_components/butterflymx/manifest.json`. You must update the `requirements` section to point to your private GitHub repository where you have hosted the python library code.
    
    You will need a **GitHub Personal Access Token** (Classic) with `repo` scope.
    
    Format:
    ```json
    "requirements": [
        "git+https://YOUR_GITHUB_TOKEN@github.com/YOUR_USERNAME/butterflymx-client.git#egg=butterflymx-client"
    ]
    ```

    **Where does the token go?**
    The token is inserted directly into the URL, after `https://` and before `@github.com`.
    
    *   **Result**: `git+https://ghp_MySecretToken123@github.com/myusername/butterflymx-client.git#egg=butterflymx-client`
    
    *Replace `YOUR_GITHUB_TOKEN` and `YOUR_USERNAME` with your actual details.*

3.  **Restart Home Assistant**: Restart your instance to load the new component.

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
