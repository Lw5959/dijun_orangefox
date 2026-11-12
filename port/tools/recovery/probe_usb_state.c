// SPDX-License-Identifier: GPL-3.0-or-later
// 独立记录 USB 属性和恢复进程等待点，不调用 HAL、不改属性或分区。
// 从 Recovery 的 cmd 动作启动后立即退出父进程，避免占用 GUI 动作线程。
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/system_properties.h>
#include <time.h>
#include <unistd.h>

static int read_text(const char *path, char *data, size_t capacity) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t size = read(fd, data, capacity - 1);
    close(fd);
    if (size < 0) return -1;
    data[size] = 0;
    data[strcspn(data, "\r\n")] = 0;
    return 0;
}

static void record_threads(int log_fd) {
    DIR *processes = opendir("/proc");
    if (!processes) return;
    struct dirent *entry;
    while ((entry = readdir(processes))) {
        if (entry->d_name[0] < '0' || entry->d_name[0] > '9') continue;
        char path[256], name[64];
        snprintf(path, sizeof(path), "/proc/%s/comm", entry->d_name);
        if (read_text(path, name, sizeof(name))) continue;
        if (strcmp(name, "recovery") && strcmp(name, "minadbd") && strcmp(name, "adbd")) continue;
        snprintf(path, sizeof(path), "/proc/%s/task", entry->d_name);
        DIR *tasks = opendir(path);
        if (!tasks) continue;
        struct dirent *task;
        while ((task = readdir(tasks))) {
            if (task->d_name[0] < '0' || task->d_name[0] > '9') continue;
            char wait[128];
            snprintf(path, sizeof(path), "/proc/%s/task/%s/wchan", entry->d_name, task->d_name);
            if (!read_text(path, wait, sizeof(wait)))
                dprintf(log_fd, "pid=%s tid=%s name=%s wait=%s\n", entry->d_name, task->d_name, name, wait);
        }
        closedir(tasks);
    }
    closedir(processes);
}

static void record_recovery_tail(int log_fd) {
    int fd = open("/tmp/recovery.log", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return;
    if (lseek(fd, -2048, SEEK_END) < 0) lseek(fd, 0, SEEK_SET);
    char data[2048];
    ssize_t size = read(fd, data, sizeof(data));
    close(fd);
    if (size > 0) {
        dprintf(log_fd, "recovery_log_tail_begin\n");
        write(log_fd, data, size);
        dprintf(log_fd, "\nrecovery_log_tail_end\n");
    }
}

static void record_boot_request(int log_fd) {
    // 仅读取 BCB 的启动请求，不修改 misc，也不触及后面的槽位元数据。
    int fd = open("/dev/block/by-name/misc", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return;
    char message[832] = {0};
    ssize_t size = read(fd, message, sizeof(message));
    close(fd);
    if (size != (ssize_t)sizeof(message)) return;
    message[31] = 0;
    message[831] = 0;
    dprintf(log_fd, "bcb_command=%s\nbcb_has_fastboot=%d\n", message,
            strstr(message + 64, "--fastboot") != NULL);
}

int main(int argc, char **argv) {
    const char *log = argc == 2 ? argv[1] : "/data/media/0/Fox/dijun-usb-state.log";
    pid_t child = fork();
    if (child < 0) return 1;
    if (child) return 0;
    setsid();
    signal(SIGHUP, SIG_IGN);
    // 不继承 ORS 输出 FIFO；否则客户端会等到诊断进程结束才收到 EOF。
    for (int fd = 0; fd < 1024; ++fd) close(fd);
    int null_fd = open("/dev/null", O_RDWR);
    if (null_fd >= 0) {
        dup2(null_fd, 0); dup2(null_fd, 1); dup2(null_fd, 2);
        if (null_fd > 2) close(null_fd);
    }
    int log_fd = open(log, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (log_fd < 0) _exit(2);
    dprintf(log_fd, "dijun USB read-only observer pid=%d\n", getpid());
    const char *properties[] = {"sys.usb.config", "sys.usb.state", "sys.usb.ffs.ready",
        "sys.usb.ffs.mtp.ready", "init.svc.recovery", "init.svc.adbd",
        "init.svc.fastbootd", "sys.powerctl", "ro.bootmode"};
    char previous[1024] = "";
    // 最多运行三分钟，等待点每秒记录；保留阶段变化时的日志，重启后也能取证。
    for (int tick = 0; tick < 3600; ++tick) {
        char state[1024] = "", value[PROP_VALUE_MAX];
        size_t used = 0;
        for (size_t i = 0; i < sizeof(properties) / sizeof(properties[0]); ++i) {
            __system_property_get(properties[i], value);
            used += snprintf(state + used, sizeof(state) - used, "%s=%s\n", properties[i], value);
        }
        int changed = strcmp(state, previous);
        if (changed || tick % 20 == 0) {
            struct timespec now;
            clock_gettime(CLOCK_BOOTTIME, &now);
            dprintf(log_fd, "time=%lld.%03ld\n%s", (long long)now.tv_sec, now.tv_nsec / 1000000, state);
            strcpy(previous, state);
            record_threads(log_fd);
            record_boot_request(log_fd);
            if (changed || tick % 200 == 0) record_recovery_tail(log_fd);
            fsync(log_fd);
        }
        usleep(50000);
    }
    close(log_fd);
    _exit(0);
}
