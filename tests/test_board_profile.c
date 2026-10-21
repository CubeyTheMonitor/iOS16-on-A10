#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../loader/board_check.h"
int main(void)
{
    struct fm_map map = {0};
    assert(exynos_check_board(NULL) == 0x300);
    assert(exynos_check_board(&map) == 0x300);
    map.valid = 1;
    strcpy(map.model, EXYNOS_BOARD_MODEL " SEA OPEN 00");
#if defined(PORT_BOARD_A10)
    assert(exynos_check_board(&map) == 0x301);
    map.reserved = 1;
    map.reserve[0] = (struct fm_range){EXYNOS_FB_ADDRESS, EXYNOS_FB_STRIDE * EXYNOS_FB_HEIGHT - 1};
    assert(exynos_check_board(&map) == 0x301);
    map.reserve[0].size++;
    assert(exynos_check_board(&map) == 0);
    map.reserve[0].start++;
    assert(exynos_check_board(&map) == 0x301);
    map.reserve[0] = (struct fm_range){UINT64_MAX - 1, 4};
    assert(exynos_check_board(&map) == 0x301);
    map.reserve[0] = (struct fm_range){EXYNOS_FB_ADDRESS, 0x1400000};
#endif
    assert(exynos_check_board(&map) == 0);
    strcpy(map.model, EXYNOS_BOARD_MODEL "5");
    assert(exynos_check_board(&map) == 0x300);
    strcpy(map.model, "Samsung unsupported");
    assert(exynos_check_board(&map) == 0x300);
    puts("board guard passed");
}
