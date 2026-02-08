#
# Copyright (C) 2025 w9315273
#
# This is free software, licensed under the MIT License.
#

include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-adguardhome
PKG_VERSION:=2.3.1
PKG_RELEASE:=1

PKG_LICENSE:=MIT
PKG_LICENSE_FILES:=LICENSE
PKG_MAINTAINER:=w9315273
PKG_BUILD_DEPENDS:=luci-base/host

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-adguardhome
	SECTION:=luci
	CATEGORY:=LuCI
	SUBMENU:=3. Applications
	TITLE:=LuCI app for AdGuardHome
	PKG_MAINTAINER:=https://github.com/w9315273/luci-app-adguardhome
	PKGARCH:=all
	DEPENDS:=+uclient-fetch +tar
endef

define Package/luci-app-adguardhome/description
	LuCI support for AdGuardHome (nftables-based DNS redirect).
	This package does NOT include the AdGuardHome core binary.
endef

define Build/Prepare
endef

define Build/Compile
endef

define Package/luci-app-adguardhome/conffiles
/etc/config/AdGuardHome
endef

define Package/luci-app-adguardhome/install
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci
	cp -pR ./luasrc/* $(1)/usr/lib/lua/luci

	cp -pR ./root/* $(1)/

	$(INSTALL_DATA) ./root/usr/share/AdGuardHome/adguardhome.nft.tpl \
		$(1)/usr/share/AdGuardHome/adguardhome.nft.tpl

	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/i18n
	po2lmo ./po/zh-cn/AdGuardHome.po \
		$(1)/usr/lib/lua/luci/i18n/AdGuardHome.zh-cn.lmo
endef

define Package/luci-app-adguardhome/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] && exit 0

/etc/init.d/AdGuardHome enable >/dev/null 2>&1

enable=$$(uci get AdGuardHome.AdGuardHome.enabled 2>/dev/null)
if [ "$$enable" = "1" ]; then
	/etc/init.d/AdGuardHome reload
fi

rm -f /tmp/luci-indexcache
rm -f /tmp/luci-modulecache/*
/etc/init.d/rpcd reload

exit 0
endef

define Package/luci-app-adguardhome/prerm
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

$(eval $(call BuildPackage,luci-app-adguardhome))
