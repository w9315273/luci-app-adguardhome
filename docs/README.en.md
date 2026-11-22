<!-- plugin-list: en w9315273/luci-app-adguardhome -->
<table>
  <tr><th colspan="3">My plugin list</th></tr>
  <tr valign="middle">
    <td><a href="https://github.com/w9315273/luci-app-adguardhome"><img src="https://img.shields.io/github/stars/w9315273/luci-app-adguardhome?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="AdGuard Home for LuCI · GitHub stars"></a></td>
    <td><strong>AdGuard Home for LuCI</strong></td>
    <td>AdGuard Home management</td>
  </tr>
  <tr valign="middle">
    <td><a href="https://github.com/w9315273/luci-app-pulse"><img src="https://img.shields.io/github/stars/w9315273/luci-app-pulse?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="LuCI Pulse · GitHub stars"></a></td>
    <td><strong><a href="https://github.com/w9315273/luci-app-pulse">LuCI Pulse</a></strong></td>
    <td>System monitor</td>
  </tr>
  <tr valign="middle">
    <td><a href="https://github.com/w9315273/openwrt-traffic-stats"><img src="https://img.shields.io/github/stars/w9315273/openwrt-traffic-stats?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="OpenWrt Traffic Stats · GitHub stars"></a></td>
    <td><strong><a href="https://github.com/w9315273/openwrt-traffic-stats">OpenWrt Traffic Stats</a></strong></td>
    <td>Per-device traffic</td>
  </tr>
</table>
<!-- /plugin-list -->

# AdGuard Home for LuCI

Manage AdGuard Home in OpenWrt's LuCI interface. LuCI pages are rewritten in JavaScript, with an rpcd + ucode backend and nftables-based DNS forwarding.

[简体中文](README.md) · [English](README.en.md)

## Features

- Service status and core updates
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
