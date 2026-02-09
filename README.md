> [!TIP]
> 由于 OpenWrt 25.12 开始使用 `apk` 包管理器，
> 本项目目前以 **未签名的 APK** 形式发布。
>
> 一键安装命令（仅限 `25.12` 以上）：
> ```
> uclient-fetch -qO- https://raw.githubusercontent.com/w9315273/luci-app-adguardhome/master/install.sh | sh
> ```
> 
>

### luci-app-adguardhome（nft 版）简要说明

面向已熟悉原项目的用户: 仅将 **DNS** 重定向从 `iptables` 迁移到 `nftables`, 核心语义不变

### 变更概览
- `iptables` → `nftables`：使用 nft 应用/清理规则 `/var/etc/adguardhome.nft`
- 模板路径：`/usr/share/AdGuardHome/adguardhome.nft.tpl`

### 模板与默认行为
![01](https://github.com/user-attachments/assets/904948fc-e83e-4246-8f61-b6c978a7e073)
![02](https://github.com/user-attachments/assets/14d51f1f-f7e7-43d4-a91c-cb95a8a9e4ef)


> [!TIP]
> 从 **v2.2.0** 开始，可在 LuCI 界面的 **WAN 接口** 选项中直接选择需要排除的网卡，
> 无需再手动编辑 `adguardhome.nft.tpl` 模板文件。
>
> 该选项 **仅在「重定向」模式下生效**，
> 用于避免将来自公网接口的 DNS 请求重定向到本机，
> 从而防止 AdGuardHome 被暴露为公共 DNS 解析器。
>
> 请仅选择 **直接面向公网的接口**（如 `eth0`、`pppoe-wan` 等）

### 声明
本项目基于 https://github.com/rufengsuixing/luci-app-adguardhome 修改。
原项目未提供明确的开源协议，当前仅用于个人学习研究，不用于商业用途。如原作者有任何异议，请联系我处理。
