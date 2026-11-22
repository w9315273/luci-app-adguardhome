<!-- plugin-list: zh w9315273/luci-app-adguardhome -->
<table>
  <tr><th colspan="3">我的插件列表</th></tr>
  <tr valign="middle">
    <td><img src="https://img.shields.io/github/stars/w9315273/luci-app-adguardhome?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="AdGuard Home for LuCI · GitHub 星数"></td>
    <td><strong>AdGuard Home for LuCI</strong></td>
    <td>AdGuard Home 管理</td>
  </tr>
  <tr valign="middle">
    <td><img src="https://img.shields.io/github/stars/w9315273/luci-app-pulse?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="LuCI Pulse · GitHub 星数"></td>
    <td><strong><a href="https://github.com/w9315273/luci-app-pulse">LuCI Pulse</a></strong></td>
    <td>系统监控</td>
  </tr>
  <tr valign="middle">
    <td><img src="https://img.shields.io/github/stars/w9315273/openwrt-traffic-stats?style=flat&amp;label=%E2%98%85&amp;color=57606a" height="16" alt="OpenWrt Traffic Stats · GitHub 星数"></td>
    <td><strong><a href="https://github.com/w9315273/openwrt-traffic-stats">OpenWrt Traffic Stats</a></strong></td>
    <td>设备流量统计</td>
  </tr>
</table>
<!-- /plugin-list -->

# AdGuard Home for LuCI

在 OpenWrt 的 LuCI 界面中管理 AdGuard Home。使用 JavaScript 重写 LuCI 页面，后端采用 rpcd + ucode，并适配 nftables DNS 转发。

[简体中文](README.md) · [English](README.en.md)

## 功能

- 服务状态查看与核心更新
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
