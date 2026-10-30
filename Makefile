#
# Copyright (C) 2025 w9315273
#

include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-adguardhome-tk
PKG_VERSION:=2.6.0
PKG_RELEASE:=3

PKG_MAINTAINER:=w9315273
PKG_BUILD_DEPENDS:=luci-base/host

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-adguardhome-tk
	SECTION:=luci
	CATEGORY:=LuCI
	SUBMENU:=3. Applications
	TITLE:=LuCI app for AdGuardHome
	PKG_MAINTAINER:=https://github.com/w9315273/luci-app-adguardhome
	PKGARCH:=all
	PROVIDES:=luci-app-adguardhome
	CONFLICTS:=luci-app-adguardhome
	DEPENDS:=+luci-base +rpcd-mod-ucode +uclient-fetch +jsonfilter +flock +ca-bundle +!(PACKAGE_libustream-openssl||PACKAGE_libustream-wolfssl):libustream-mbedtls +tar
endef

define Package/luci-app-adguardhome-tk/description
	LuCI support for AdGuardHome (nftables-based DNS redirect).
	This package does NOT include the AdGuardHome core binary.
endef

define Package/luci-i18n-adguardhome-tk-zh-cn
	SECTION:=luci
	CATEGORY:=LuCI
	HIDDEN:=1
	TITLE:=AdGuardHome - Simplified Chinese translation
	PKGARCH:=all
	PROVIDES:=luci-i18n-adguardhome-zh-cn
	CONFLICTS:=luci-i18n-adguardhome-zh-cn
	DEPENDS:=luci-app-adguardhome-tk
	DEFAULT:=LUCI_LANG_zh_Hans
endef

define Package/luci-i18n-adguardhome-tk-zh-cn/description
	Simplified Chinese translation for luci-app-adguardhome-tk.
endef

define Build/Prepare
endef

define Build/Compile
endef

define Package/luci-app-adguardhome-tk/conffiles
/etc/config/AdGuardHome
endef

define Package/luci-app-adguardhome-tk/install
	cp -pR ./root/* $(1)/
endef

define Package/luci-i18n-adguardhome-tk-zh-cn/install
	$(INSTALL_DIR) $(1)/etc/uci-defaults
	echo "uci set luci.languages.zh_cn='简体中文 (Simplified Chinese)'; uci commit luci" \
		> $(1)/etc/uci-defaults/luci-i18n-adguardhome-tk-zh-cn
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/i18n
	po2lmo ./po/zh-cn/AdGuardHome.po \
		$(1)/usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo
endef

define Package/luci-app-adguardhome-tk/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] && exit 0

/etc/init.d/AdGuardHome enable >/dev/null 2>&1

enable=$$(uci get AdGuardHome.AdGuardHome.enabled 2>/dev/null)
if [ "$$enable" = "1" ]; then
	/etc/init.d/AdGuardHome reload
fi

# Remove the former menu definition when upgrading.
rm -f /usr/share/luci/menu.d/luci-app-adguardhome-js.json
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.*
rm -f /tmp/luci-modulecache/*
/etc/init.d/rpcd reload

exit 0
endef

define Package/luci-app-adguardhome-tk/prerm
#!/bin/sh
if [ -z "$${IPKG_INSTROOT}" ]; then
	/etc/init.d/AdGuardHome disable
	/etc/init.d/AdGuardHome stop 2>/dev/null || true

	uci -q batch <<-EOF >/dev/null 2>&1
		delete ucitrack.@AdGuardHome[-1]
		commit ucitrack
EOF
fi

exit 0
endef

$(eval $(call BuildPackage,luci-app-adguardhome-tk))

$(eval $(call BuildPackage,luci-i18n-adguardhome-tk-zh-cn))
