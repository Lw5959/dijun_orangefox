/* SPDX-License-Identifier: GPL-3.0-or-later
 * 在真机调用 GUI 同一入口并留出自动停止窗口；0 用于关闭，不触发新的震动。 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2 || argc > 3) {
        fprintf(stderr, "usage: probe_haptic_timeout duration_ms [replacement_ms]\n");
        return 2;
    }
    int duration = atoi(argv[1]);
    int replacement = argc == 3 ? atoi(argv[2]) : 0;
    if (duration < 0 || duration > 1000 || replacement < 0 || replacement > 1000)
        return 2;
    int (*vibrate)(int) = (int (*)(int))dlsym(RTLD_DEFAULT, "_Z7vibratei");
    Dl_info info;
    if (!vibrate || !dladdr((void *)vibrate, &info) ||
        !strstr(info.dli_fname, "libdijun_drm.so")) {
        fprintf(stderr, "the timed O1 adapter is not preloaded\n");
        return 1;
    }
    printf("provider=%s\n", info.dli_fname);
    int result = vibrate(duration);
    printf("on(%d)=%d\n", duration, result);
    if (argc == 3 && result == 0) {
        usleep(50000);
        result = vibrate(replacement);
        printf("replacement(%d)=%d\n", replacement, result);
    }
    int longest = duration > replacement ? duration : replacement;
    usleep((longest + 250) * 1000);
    printf("automatic-stop observation window ended\n");
    int cleanup = vibrate(0);
    printf("cleanup_off=%d\n", cleanup);
    return result || cleanup;
}
