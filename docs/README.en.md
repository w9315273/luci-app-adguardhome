<!-- plugin-list: en w9315273/luci-app-adguardhome -->
<table>
  <tr><th colspan="3">My plugin list</th></tr>
  <tr valign="top">
    <td><a href="https://github.com/w9315273/luci-app-adguardhome"><img src="https://img.shields.io/github/stars/w9315273/luci-app-adguardhome?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="AdGuard Home for LuCI · GitHub stars"></a></td>
    <td><strong>AdGuard Home for LuCI</strong></td>
    <td width="360"><details><summary>AdGuard Home management</summary><a href="https://raw.githubusercontent.com/w9315273/luci-app-adguardhome/HEAD/docs/screenshots/base-en.png"><img src="https://raw.githubusercontent.com/w9315273/luci-app-adguardhome/HEAD/docs/screenshots/base-en.png" width="100%" alt="AdGuard Home for LuCI · screenshot"></a></details></td>
  </tr>
  <tr valign="top">
    <td><a href="https://github.com/w9315273/luci-app-pulse"><img src="https://img.shields.io/github/stars/w9315273/luci-app-pulse?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="LuCI Pulse · GitHub stars"></a></td>
    <td><strong><a href="https://github.com/w9315273/luci-app-pulse">LuCI Pulse</a></strong></td>
    <td width="360"><details><summary>System monitor</summary><a href="https://raw.githubusercontent.com/w9315273/luci-app-pulse/HEAD/docs/screenshot-en.png"><img src="https://raw.githubusercontent.com/w9315273/luci-app-pulse/HEAD/docs/screenshot-en.png" width="100%" alt="LuCI Pulse · screenshot"></a></details></td>
  </tr>
  <tr valign="top">
    <td><a href="https://github.com/w9315273/openwrt-traffic-stats"><img src="https://img.shields.io/github/stars/w9315273/openwrt-traffic-stats?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="OpenWrt Traffic Stats · GitHub stars"></a></td>
    <td><strong><a href="https://github.com/w9315273/openwrt-traffic-stats">OpenWrt Traffic Stats</a></strong></td>
    <td width="360"><details><summary>Per-device traffic</summary><a href="https://raw.githubusercontent.com/w9315273/openwrt-traffic-stats/HEAD/docs/images/overview.png"><img src="https://raw.githubusercontent.com/w9315273/openwrt-traffic-stats/HEAD/docs/images/overview.png" width="100%" alt="OpenWrt Traffic Stats · screenshot"></a></details></td>
  </tr>
</table>
<!-- /plugin-list -->

# AdGuard Home for LuCI

Manage AdGuard Home in OpenWrt's LuCI interface. LuCI pages are rewritten in JavaScript, with an rpcd + ucode backend and nftables-based DNS forwarding.

[简体中文](README.md) · [English](README.en.md)

## Features

- View service status and update the core. Before replacing an installed core, the updater backs up the current binary and YAML configuration together on the router, including when you force an update to the same version. To repair a damaged core, use **Force update** or **Upload core** in **Basic Settings**. The installer saves the damaged file and any existing YAML before replacing the core.
- In **Basic Settings**, choose **Upload core** and select the `AdGuardHome` Linux binary or official `.tar.gz` archive for your router’s architecture. You can leave SHA-256 blank, enter a plain digest, or paste GitHub’s value with its `sha256:` prefix. If you enter a digest, installation proceeds only when the selected file matches it. For a `.tar.gz` upload, use the digest of the archive itself. Manual installation works offline and backs up the current core and YAML before replacement. [Official AdGuard Home releases](https://github.com/AdguardTeam/AdGuardHome/releases)
- Under **Backup / Restore**, create separate backups of the core and YAML configuration. To roll back a version, choose **Restore both** on an entry containing the core and YAML. The plugin verifies both files, restores them together, then starts the service if enabled. **Restore core** and **Restore configuration** are also available individually. **Delete** removes the whole entry. Legacy `.prev` entries support restoring the core.
- Backups are stored alongside the binary in `<core filename>.backups/`. The router keeps the latest 3 automatic backups, 5 manual core backups, and 5 manual YAML backups. It removes older backups in the same category only after a new backup succeeds. In older manual backups that contain both the core and YAML, each component counts toward its own limit and expires independently.
- Before backing up or restoring YAML, the plugin runs the core’s `--check-config`. A failed check stops the operation. If the core is missing, the operation continues and LuCI reports that validation was skipped.
- DNS handling through firewall forwarding, dnsmasq upstream, or port 53 replacement
- YAML configuration editing, validation, and web login password changes
- Runtime logs with reverse order, local timestamps, download, and a verbose logging toggle

> [!TIP]
> **Quick installation**
>
> Run in the terminal of an OpenWrt router using the APK package manager:
>
> ```sh
> uclient-fetch -O /tmp/install-adguardhome.sh https://raw.githubusercontent.com/w9315273/luci-app-adguardhome/main/scripts/install.sh && sh /tmp/install-adguardhome.sh
> ```

## Screenshots

### Basic settings

![Basic settings](screenshots/base-en.png)

### Manual configuration

![Manual configuration](screenshots/manual-en.png)

### Logs

![Runtime logs](screenshots/log-en.png)
