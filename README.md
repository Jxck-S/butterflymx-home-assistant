# ButterflyMX Home Assistant Integration
<img src="assets/logo.png" width="300" />

This integration allows you to control your ButterflyMX access points (doors) and view message/call history from Home Assistant.

> [!WARNING]
> **For educational and personal use only.** This integration is an unofficial, independent project. It is not affiliated with, endorsed by, or supported by ButterflyMX. It works by using the same private API as the official mobile app, which can change or stop working at any time without notice.
>
> - Use it only with your own account and only for doors you are authorized to access.
> - You are responsible for complying with ButterflyMX's Terms of Service and your building's policies.
> - This software is provided "as is", without warranty of any kind. The authors are not liable for any damages, account suspensions, or security issues resulting from its use.

## Installation

### HACS (recommended)
1. In HACS, open the menu (⋮) > **Custom repositories**.
2. Add `https://github.com/Jxck-S/butterflymx-home-assistant` with category **Integration**.
3. Search for **ButterflyMX** in HACS and download it.
4. Restart Home Assistant.

### Manual
1. Copy `custom_components/butterflymx` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

Home Assistant installs the [butterflymx-client](https://github.com/Jxck-S/butterflymx-client) library automatically.

### Setup
1. Go to **Settings > Devices & Services**.
2. Click **Add Integration** and search for "ButterflyMX".
3. Enter your ButterflyMX email and password.

## Entities

*   **Locks**: Each accessible Door/Intercom will appear as a Lock entity.
    *   **Unlock**: Pressing unlock will trigger the `open()` command.
*   **Sensors**:
    *   **Last Message**: Shows the body of the most recent message. Attributes include timestamp and source.
    *   **Last Call**: Shows the device and status of the most recent call. Attributes include type and image URL.
    *   **Last Access**: Shows the door and type of the most recent door release.
*   **Images**: Latest call, message, and access snapshots.

## License

[MIT](LICENSE). See the disclaimer at the top: this is an unofficial project, not affiliated with ButterflyMX.
