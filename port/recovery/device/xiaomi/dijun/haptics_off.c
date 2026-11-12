/* SPDX-License-Identifier: GPL-3.0-or-later
 * Recovery 退出会带走定时线程，由 init 再执行一次 off，防止残留播放。 */
extern int vibrate(int milliseconds) __asm__("_Z7vibratei");

int main(void) {
    return vibrate(0) == 0 ? 0 : 1;
}
