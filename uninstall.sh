#!/system/bin/sh
MODDIR=${0%/*}
. "$MODDIR/common.sh"
# KSU 在正常开机时处理待卸载模块。若 OTA/其他工具已换过 Recovery，不能覆盖它。
restore_recovery
