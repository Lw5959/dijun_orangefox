// SPDX-License-Identifier: GPL-3.0-or-later
// O1 的原厂 HAL 在 Recovery 中启动波形后未按 timeoutMs 自动停止。
// 沿用 OrangeFox USE_QTI_AIDL_HAPTICS_FIX_OFF 的显式 off 思路；只使用
// Binder NDK 的 C ABI，避免把 donor 与 NDK 的 C++ shared_ptr 混用。
#include <android/binder_ibinder.h>
#include <android/binder_parcel.h>
#include <android/binder_status.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

// binder_manager.h 是平台头，不随 NDK 发布；Recovery 的实际 libbinder_ndk
// 已导出这个 C 接口。声明保持 AOSP binder_manager.h 的原始签名。
extern "C" AIBinder* AServiceManager_checkService(const char* instance);

namespace {
constexpr char kDescriptor[] = "android.hardware.vibrator.IVibrator";
constexpr char kService[] = "android.hardware.vibrator.IVibrator/default";
// 冻结的 AIDL V1：getCapabilities=1、off=2、on=3；on 的参数为
// int timeoutMs 和 IVibratorCallback Binder（无回调写 null）。后续版本保持不变。
// hardware/interfaces/vibrator/aidl/aidl_api/android.hardware.vibrator/1/
constexpr transaction_code_t kOff = 2;
constexpr transaction_code_t kOn = 3;
pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
uint64_t generation;
AIBinder_Class* binder_class;

void* on_create(void* args) { return args; }
void on_destroy(void*) {}
binder_status_t on_transact(AIBinder*, transaction_code_t, const AParcel*, AParcel*) {
    return STATUS_UNKNOWN_TRANSACTION;
}

int transact(AIBinder* binder, transaction_code_t code, int duration_ms = 0) {
    AParcel *input = nullptr, *output = nullptr;
    AStatus* reply = nullptr;
    binder_status_t status = AIBinder_prepareTransaction(binder, &input);
    if (status == STATUS_OK && code == kOn)
        status = AParcel_writeInt32(input, duration_ms);
    if (status == STATUS_OK && code == kOn)
        status = AParcel_writeStrongBinder(input, nullptr);
    if (status == STATUS_OK)
        status = AIBinder_transact(binder, code, &input, &output, 0);
    if (status == STATUS_OK)
        status = AParcel_readStatusHeader(output, &reply);
    const bool ok = status == STATUS_OK && reply && AStatus_isOk(reply);
    if (!ok)
        fprintf(stderr, "dijun-haptics: transaction %u failed: transport=%d\n", code, status);
    if (reply) AStatus_delete(reply);
    if (input) AParcel_delete(input);
    if (output) AParcel_delete(output);
    return ok ? 0 : -EIO;
}

struct StopRequest {
    AIBinder* binder;
    uint64_t generation;
    timespec deadline;
};

void* stop_after_deadline(void* argument) {
    auto* request = static_cast<StopRequest*>(argument);
    int rc;
    do {
        rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &request->deadline, nullptr);
    } while (rc == EINTR);
    pthread_mutex_lock(&lock);
    // 后来的 on() 已替换旧波形时，旧定时器不能提前关闭新请求。
    if (request->generation == generation) {
        const int result = transact(request->binder, kOff);
        fprintf(stderr, "dijun-haptics: timed off generation=%llu result=%d\n",
                static_cast<unsigned long long>(generation), result);
    }
    pthread_mutex_unlock(&lock);
    AIBinder_decStrong(request->binder);
    free(request);
    return nullptr;
}
}  // namespace

int vibrate(int timeout_ms) {
    if (timeout_ms > 10000) timeout_ms = 1000;  // 保留 donor 的时长上限规则。
    pthread_mutex_lock(&lock);
    AIBinder* binder = AServiceManager_checkService(kService);
    if (!binder) {
        pthread_mutex_unlock(&lock);
        return -ENODEV;
    }
    if (!binder_class)
        binder_class = AIBinder_Class_define(kDescriptor, on_create, on_destroy, on_transact);
    if (!binder_class || !AIBinder_associateClass(binder, binder_class)) {
        AIBinder_decStrong(binder);
        pthread_mutex_unlock(&lock);
        return -EINVAL;
    }
    ++generation;
    if (timeout_ms <= 0) {
        const int result = transact(binder, kOff);
        AIBinder_decStrong(binder);
        pthread_mutex_unlock(&lock);
        return result;
    }
    auto* request = static_cast<StopRequest*>(calloc(1, sizeof(StopRequest)));
    if (!request) {
        transact(binder, kOff);
        AIBinder_decStrong(binder);
        pthread_mutex_unlock(&lock);
        return -ENOMEM;
    }
    int result = transact(binder, kOn, timeout_ms);
    if (result == 0) {
        request->binder = binder;
        request->generation = generation;
        clock_gettime(CLOCK_MONOTONIC, &request->deadline);
        request->deadline.tv_sec += timeout_ms / 1000;
        request->deadline.tv_nsec += (timeout_ms % 1000) * 1000000L;
        if (request->deadline.tv_nsec >= 1000000000L) {
            ++request->deadline.tv_sec;
            request->deadline.tv_nsec -= 1000000000L;
        }
        pthread_t thread;
        result = pthread_create(&thread, nullptr, stop_after_deadline, request);
        if (result == 0) {
            pthread_detach(thread);
            fprintf(stderr, "dijun-haptics: on %d ms generation=%llu\n", timeout_ms,
                    static_cast<unsigned long long>(generation));
        }
    }
    if (result != 0) {
        // 已经启动但无法安排停止时立即关闭，不能留下无限播放的波形。
        transact(binder, kOff);
        AIBinder_decStrong(binder);
        free(request);
    }
    pthread_mutex_unlock(&lock);
    return result;
}
