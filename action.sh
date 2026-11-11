#!/system/bin/sh
MODDIR=${0%/*}
. "$MODDIR/common.sh"
check_device && select_current_slot && check_partition || exit 1
[ "$(cat "$MODDIR/installed-slot")" = "$RECOVERY_SLOT" ] || { fail "系统启动位置已变化，请重新配置恢复镜像"; exit 1; }
[ "$(digest "$RECOVERY_BLOCK")" = "$FOX_SHA256" ] || { fail "当前不是本包 OrangeFox，请重新安装模块"; exit 1; }
echo "正在重启进入 OrangeFox Recovery。"
/system/bin/reboot recovery
