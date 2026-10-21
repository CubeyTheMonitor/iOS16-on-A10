/* Model selection is a guard, not hardware authentication. */
#pragma once
#include "fdt_memory.h"
#include "../include/exynos_profile.h"

static int exynos_check_board(const struct fm_map *map)
{
    size_t length = sizeof(EXYNOS_BOARD_MODEL) - 1;
    if (!map || !map->valid ||
        !fm_prefix((const unsigned char *)map->model, sizeof(map->model), EXYNOS_BOARD_MODEL) ||
        (map->model[length] && map->model[length] != ' ')) return 0x300;
#if defined(PORT_BOARD_A10)
    /* Full pixel extent must belong to a fixed reservation. Actual scanout
     * address/format/stride and firmware ownership still need validation. */
    if (map->reserved > FM_MAX_RESERVED) return 0x301;
    for (uint32_t i = 0; i < map->reserved; i++) {
        const struct fm_range *r = &map->reserve[i];
        if (r->size > UINT64_MAX - r->start) return 0x301;
        if (EXYNOS_FB_ADDRESS >= r->start && EXYNOS_FB_ADDRESS - r->start < r->size &&
            (uint64_t)EXYNOS_FB_STRIDE * EXYNOS_FB_HEIGHT <=
                r->size - (EXYNOS_FB_ADDRESS - r->start)) return 0;
    }
    return 0x301;
#else
    return 0;
#endif
}
