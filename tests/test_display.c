/* Exercise both board renderers on ordinary RAM with bounds sanitizers. */
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include "../include/exynos_profile.h"
static struct {
    uint32_t before[16];
    uint32_t pixels[EXYNOS_FB_WIDTH * EXYNOS_FB_HEIGHT];
    uint32_t after[16];
} buffer;
#define FBTEXT_BUFFER buffer.pixels
#include "../loader/fbtext.h"
int main(void)
{
    for (unsigned i = 0; i < 16; i++) buffer.before[i] = buffer.after[i] = 0x5ac3a5c3;
    fill(INT_MIN, INT_MAX, C_BG);
    assert(buffer.pixels[0] == C_BG);
    assert(buffer.pixels[FB_W*FB_H-1] == C_BG);
    draw_char(-1, 0, 'A', C_OK);
    draw_char(INT_MAX, INT_MAX, 'A', C_OK);
    draw_char(0, -1, 'A', C_OK);
    draw_char(COLS - 1, ROWS - 1, 'Z', C_OK);
    draw_char(COLS, ROWS, 'Z', C_ERR);
    for (int i = 0; i < ROWS * 4; i++) {
        say("EXYNOS DISPLAY BOUNDS", C_FG);
        say_hex("VALUE: ", (u64)i, 16);
    }
    assert(line >= 0 && line <= ROWS);
    assert(EXYNOS_FB_STRIDE == FB_W * 4);
    for (unsigned i = 0; i < 16; i++) {
        assert(buffer.before[i] == 0x5ac3a5c3);
        assert(buffer.after[i] == 0x5ac3a5c3);
    }
    printf("display bounds passed: %dx%d, stride %d\n", FB_W, FB_H, EXYNOS_FB_STRIDE);
}
