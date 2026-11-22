<!-- plugin-list: zh w9315273/luci-app-adguardhome -->
<table>
  <tr><th colspan="3">我的插件列表</th></tr>
  <tr valign="top">
    <td><a href="https://github.com/w9315273/luci-app-adguardhome"><img src="https://img.shields.io/github/stars/w9315273/luci-app-adguardhome?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="AdGuard Home for LuCI · GitHub 星数"></a></td>
    <td><strong>AdGuard Home for LuCI</strong></td>
    <td width="360"><details><summary>AdGuard Home 管理</summary><a href="https://raw.githubusercontent.com/w9315273/luci-app-adguardhome/HEAD/docs/screenshots/base-zh-cn.png"><img src="https://raw.githubusercontent.com/w9315273/luci-app-adguardhome/HEAD/docs/screenshots/base-zh-cn.png" width="100%" alt="AdGuard Home for LuCI · 界面截图"></a></details></td>
  </tr>
  <tr valign="top">
    <td><a href="https://github.com/w9315273/luci-app-pulse"><img src="https://img.shields.io/github/stars/w9315273/luci-app-pulse?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="LuCI Pulse · GitHub 星数"></a></td>
    <td><strong><a href="https://github.com/w9315273/luci-app-pulse">LuCI Pulse</a></strong></td>
    <td width="360"><details><summary>系统监控</summary><a href="https://raw.githubusercontent.com/w9315273/luci-app-pulse/HEAD/docs/screenshot-zh-cn.png"><img src="https://raw.githubusercontent.com/w9315273/luci-app-pulse/HEAD/docs/screenshot-zh-cn.png" width="100%" alt="LuCI Pulse · 界面截图"></a></details></td>
  </tr>
  <tr valign="top">
    <td><a href="https://github.com/w9315273/openwrt-traffic-stats"><img src="https://img.shields.io/github/stars/w9315273/openwrt-traffic-stats?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="OpenWrt Traffic Stats · GitHub 星数"></a></td>
    <td><strong><a href="https://github.com/w9315273/openwrt-traffic-stats">OpenWrt Traffic Stats</a></strong></td>
    <td width="360"><details><summary>设备流量统计</summary><a href="https://raw.githubusercontent.com/w9315273/openwrt-traffic-stats/HEAD/docs/images/overview.png"><img src="https://raw.githubusercontent.com/w9315273/openwrt-traffic-stats/HEAD/docs/images/overview.png" width="100%" alt="OpenWrt Traffic Stats · 界面截图"></a></details></td>
  </tr>
</table>
<!-- /plugin-list -->

# AdGuard Home for LuCI

在 OpenWrt 的 LuCI 界面中管理 AdGuard Home。使用 JavaScript 重写 LuCI 页面，后端采用 rpcd + ucode，并适配 nftables DNS 转发。

[简体中文](README.md) · [English](README.en.md)

## 功能

- 服务状态查看与核心更新。替换已安装的核心前，插件会将当前核心和 YAML 配置一起备份到路由器；同版本强制更新也会创建备份。
- 在「备份/恢复」页面可分别创建核心备份和配置备份，按时间点离线恢复核心或 YAML。每条记录末尾的「删除」可移除整份备份。旧版 `.prev` 记录支持恢复核心。
- 备份保存在核心旁的 `<核心文件名>.backups/` 目录。自动备份保留最近 3 份，手动核心备份和手动 YAML 备份各保留最近 5 份。新备份成功后才清理同类中超出数量的旧备份。旧版手动备份如果同时包含核心和 YAML，两项分别计数，也分别清理。
- 备份或恢复 YAML 前会运行核心的 `--check-config`。校验失败会中止操作，未安装核心时会提示跳过校验。
- 防火墙转发、dnsmasq 上游、替代 dnsmasq 使用 53 端口等 DNS 接入方式
- YAML 配置编辑与校验、网页登录密码修改
- 运行日志查看，支持逆序、本地时间、下载和详细日志开关

> [!TIP]
> **一键安装**
>
> 在使用 APK 包管理器的 OpenWrt 路由器终端执行：
>
> ```sh
> uclient-fetch -O /tmp/install-adguardhome.sh https://raw.githubusercontent.com/w9315273/luci-app-adguardhome/main/scripts/install.sh && sh /tmp/install-adguardhome.sh zh-cn
> ```

## 截图

### 基础设置

![基础设置](screenshots/base-zh-cn.png)

### 手动设置

![手动设置](screenshots/manual-zh-cn.png)

### 日志

![运行日志](screenshots/log-zh-cn.png)
