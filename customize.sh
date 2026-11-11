#!/system/bin/sh
# KernelSU 已将包解压至 MODPATH；安装不重启，不添加任何开机刷写服务。
[ "$KSU" = true ] && [ "$BOOTMODE" = true ] || abort "请在 Android 的 KernelSU 管理器中安装"
MODDIR=$MODPATH
. "$MODDIR/common.sh"
ui_print "OrangeFox for Dijun"
ui_print "正在安装 OrangeFox，完成后可通过模块的操作按钮进入。"
set_perm_recursive "$MODPATH" 0 0 0755 0644
for script in action.sh restore.sh uninstall.sh; do
    set_perm "$MODPATH/$script" 0 0 0755
done
install_recovery || abort "OrangeFox 未安装成功，请查看上方具体原因"
ui_print "完成。先正常重启 Android 使模块生效，再点模块“操作”进入 OrangeFox。"
ui_print "恢复原厂：卸载此模块后正常重启 Android；仅禁用模块不会恢复 Recovery。"
