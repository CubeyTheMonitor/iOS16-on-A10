/* Experimental A10 values are independently sourced from uniLoader's A10
 * board and Samsung/Eureka's A10 DTS, not inferred from the A40 profile.
 * No RAM bank or partition number belongs in this header.
 */
#pragma once
#if defined(PORT_BOARD_A10) && defined(PORT_BOARD_A40)
#error "Select exactly one board"
#endif

#if defined(PORT_BOARD_A10)
#define EXYNOS_BOARD_MODEL "Samsung A10"
#define EXYNOS_BOARD_LABEL "A10 IOS16 LOADER EXPERIMENTAL"
#define EXYNOS_FB_WIDTH 720
#define EXYNOS_FB_HEIGHT 1520
#define EXYNOS_FB_ADDRESS 0xec000000
#define EXYNOS_DECON_TRIGGER 0x14860070
#define EXYNOS_DECON_VALUE 0x1281
#define EXYNOS_START_A53_WITNESS 0
#else
#define EXYNOS_BOARD_MODEL "Samsung A40"
#define EXYNOS_BOARD_LABEL "A40 IOS16 LOADER"
#define EXYNOS_FB_WIDTH 1080
#define EXYNOS_FB_HEIGHT 2340
#define EXYNOS_FB_ADDRESS 0xec000000
#define EXYNOS_DECON_TRIGGER 0x14860070
#define EXYNOS_DECON_VALUE 0x1281
#define EXYNOS_START_A53_WITNESS 1
#endif

#define EXYNOS_FB_STRIDE (EXYNOS_FB_WIDTH * 4)
#define EXYNOS_ASM_STR_INNER(x) #x
#define EXYNOS_ASM_STR(x) EXYNOS_ASM_STR_INNER(x)
