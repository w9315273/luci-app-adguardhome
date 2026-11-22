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

- 服务状态查看与核心更新。替换已安装的核心前会自动备份当前核心和 YAML，同版本强制更新也会创建备份。如果已有核心损坏，可在「基础设置」使用「强制更新」或「手动上传」修复。插件会先保留损坏的原件和已有的 YAML，随后才替换核心。
- 在「基础设置」点「手动上传」，选择适用于路由器架构的 Linux 核心文件 `AdGuardHome` 或官方 `.tar.gz` 压缩包。SHA-256 可以留空，也可以填写纯摘要或直接粘贴 GitHub 上带 `sha256:` 前缀的值。填写后，路由器会先校验所选文件，匹配后才继续安装。上传压缩包时，校验值对应压缩包本身。手动安装支持离线操作和更新前自动备份。[AdGuard Home 官方发布页](https://github.com/AdguardTeam/AdGuardHome/releases)
- 在「备份/恢复」页面可分别创建核心备份和配置备份。需要回退核心版本时，在包含核心和 YAML 的同一条记录上点「同时恢复」。插件会先校验两项，一起还原，再启动已启用的服务。也可点「恢复核心」或「恢复配置」单独还原。每条记录末尾的「删除」可移除整份备份。旧版 `.prev` 记录支持恢复核心。
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
