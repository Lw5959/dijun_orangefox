// 配套固定 donor 的 forkserver：额外的 w2 只由 recovery 的唯一调用点提供。
// 保留父进程的输出 fd；子进程启动 MTP 前关闭它，使 CLI 能正常收到 EOF。
.text
.global dijun_mtp_fork
dijun_mtp_fork:
    stp x29, x30, [sp, #-32]!
    mov x29, sp
    str w2, [sp, #16]
    bl mtp_fork
    cbnz w0, mtp_fork_return
    ldr w0, [sp, #16]
    tbnz w0, #31, mtp_child_ready
    bl mtp_close
mtp_child_ready:
    mov w0, wzr
mtp_fork_return:
    ldp x29, x30, [sp], #32
    ret
