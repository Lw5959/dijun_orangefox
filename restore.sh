#!/system/bin/sh
# 可在卸载前手动执行，成功后不重启；不依赖 KSU 的卸载钩子完成错误反馈。
MODDIR=${0%/*}
. "$MODDIR/common.sh"
restore_recovery
