/*
 * Experimental A10 / inherited A40 iOS 16 loader (fork ios-sweet) : démarré par S-Boot sur un Cortex-A53,
 * il copie le payload SWEETXNU (noyau xnu-8796 + ADT, tools mkpayload.py) ajouté par
 * pack.py --blob, prépare boot_args (révision 2, ligne de commande 608 octets), puis
 * démarre XNU sur le premier Cortex-A73 (MPIDR 0x000) par PSCI CPU_ON : les A53 n'ont
 * pas le granule 16 Ko qu'exige le noyau iOS 16. Le A53 s'éteint ensuite (CPU_OFF).
 * Tout se fait MMU et caches coupés ; le A73 démarre avec des caches froids.
 */
#include "fbtext.h"
#include "entry.h"
#include "memory.h"
#include "fdt_memory.h"
#include "payload_check.h"
#include "board_check.h"

#define PSCI_CPU_ON      0xC4000003UL
#define PSCI_CPU_OFF     0x84000002UL
#define PSCI_VERSION     0x84000000UL
#define A73_MPIDR        0x000UL

struct boot_video {
	u64 base, display, row_bytes, width, height, depth;
};

struct boot_args {
	unsigned short revision, version;
	u64 virt_base, phys_base, mem_size, top_of_kernel_data;
	struct boot_video video;
	u32 machine_type;
	u64 device_tree;
	u32 device_tree_length;
	char command_line[BOOT_LINE_LENGTH];
	u64 boot_flags, mem_size_actual;
};

_Static_assert(__builtin_offsetof(struct payload, segs) == 0x2a8, "payload header");
_Static_assert(__builtin_offsetof(struct boot_args, video) == 40, "boot_args");
_Static_assert(__builtin_offsetof(struct boot_args, command_line) == 108, "boot_args");
_Static_assert(sizeof(struct boot_args) == 736, "boot_args");

/* Readable with a debugger after a silent preflight halt. No display/MMIO is
 * used until the map, payload and the selected display profile pass.
 * Errors 1..FM_OVERLAY: memory reader; 0x100+PC_*: payload; 0x200: image;
 * 0x300/0x301: board profile/framebuffer reservation; 0x400: exception before display initialization.
 */
__attribute__((used)) static volatile struct {
	u64 signature, fdt_pa, map_pa, image_pa, image_size, esr, far;
	u32 stage, error;
} loader_diagnostics;
__attribute__((used)) static struct fm_map handoff_map;
static volatile u32 display_ready;

static __attribute__((noreturn)) void early_stop(u32 error)
{
	loader_diagnostics.error = error;
	__asm__ volatile("dsb sy" ::: "memory");
	for (;;) __asm__ volatile("wfe");
}

/* Lus par le A73 au démarrage (mémoire non cacheable des deux côtés). */
__attribute__((used)) static volatile u64 a73_entry_pa, a73_boot_args, a73_alive;
__attribute__((used)) static volatile u64 a73_mmfr0, a73_feature_error;

/*
 * Point d'entrée PSCI du A73 : x0 = context_id. Descend en EL1 si le firmware
 * nous donne EL2, puis saute dans XNU (x0 = boot_args physique), MMU coupée.
 */
__asm__(
	".text\n"
	".balign 8\n"
	"a73_start:\n"
	"	msr	daifset, #0xf\n"
	/* Profile-relative diagnostic bands; neither can exceed the panel. */
	"	mrs	x11, mpidr_el1\n"
	"	ubfx	x11, x11, #8, #8\n"		/* Aff1 : 1 = A53, 0 = A73 */
	/* Check the actual A73 before drawing or advertising it as alive. */
	"	cbnz	x11, 8f\n"
	"	mrs	x9, CurrentEL\n"
	"	cmp	x9, #4\n"
	"	b.eq	10f\n"
	"	cmp	x9, #8\n"
	"	b.eq	10f\n"
	"	adr	x10, a73_feature_error\n"
	"	mov	x9, #2\n"
	"	str	x9, [x10]\n"
	"	dsb	sy\n"
	"	b	9f\n"
	"10:\n"
	"	mrs	x9, id_aa64mmfr0_el1\n"
	"	adr	x10, a73_mmfr0\n"
	"	str	x9, [x10]\n"
	"	ubfx	x9, x9, #20, #4\n"
	"	cmp	x9, #1\n"
	"	b.eq	8f\n"
	"	adr	x10, a73_feature_error\n"
	"	mov	x9, #1\n"
	"	str	x9, [x10]\n"
	"	dsb	sy\n"
	"9:	wfe\n"
	"	b	9b\n"
	"8:\n"
	"	movz	x9, #(" EXYNOS_ASM_STR(EXYNOS_FB_ADDRESS) " >> 16), lsl #16\n"
	"	movz	x12, #(" EXYNOS_ASM_STR(EXYNOS_FB_STRIDE) " * 20 / 4)\n"	/* 20 rows, within either profile */
	"	cbz	x11, 2f\n"
	"	movz	x13, #0x00FF, lsl #16\n"	/* A53 : vert 0x0000FF00? -> rouge/vert selon ordre */
	"	movk	x13, #0xFF00\n"
	"	movz	x10, #((" EXYNOS_ASM_STR(EXYNOS_FB_HEIGHT) " - 100) * " EXYNOS_ASM_STR(EXYNOS_FB_STRIDE) " / 0x10000), lsl #16\n"
	"	movk	x10, #(((" EXYNOS_ASM_STR(EXYNOS_FB_HEIGHT) " - 100) * " EXYNOS_ASM_STR(EXYNOS_FB_STRIDE) ") & 0xffff)\n"
	"	b	3f\n"
	"2:	movz	x13, #0xFFFF, lsl #16\n"	/* A73 : blanc */
	"	movk	x13, #0xFFFF\n"
	"	movz	x10, #((" EXYNOS_ASM_STR(EXYNOS_FB_HEIGHT) " - 60) * " EXYNOS_ASM_STR(EXYNOS_FB_STRIDE) " / 0x10000), lsl #16\n"
	"	movk	x10, #(((" EXYNOS_ASM_STR(EXYNOS_FB_HEIGHT) " - 60) * " EXYNOS_ASM_STR(EXYNOS_FB_STRIDE) ") & 0xffff)\n"
	"3:	add	x9, x9, x10\n"
	"4:	str	w13, [x9], #4\n"
	"	subs	x12, x12, #1\n"
	"	b.ne	4b\n"
	"	dsb	sy\n"
	"	movz	x9, #(" EXYNOS_ASM_STR(EXYNOS_DECON_TRIGGER) " >> 16), lsl #16\n"
	"	movk	x9, #(" EXYNOS_ASM_STR(EXYNOS_DECON_TRIGGER) " & 0xffff)\n"
	"	mov	w10, #" EXYNOS_ASM_STR(EXYNOS_DECON_VALUE) "\n"
	"	str	w10, [x9]\n"
	"	dsb	sy\n"
	"	adr	x9, a73_alive\n"
	"	mov	x10, #0xA73\n"
	"	cbz	x11, 5f\n"
	"	mov	x10, #0xA53\n"
	"5:	str	x10, [x9]\n"
	"	dsb	sy\n"
	"	cbz	x11, 6f\n"
	"7:	wfe\n"
	"	b	7b\n"
	"6:\n"
	"	mrs	x9, CurrentEL\n"
	"	cmp	x9, #8\n"
	"	b.ne	1f\n"
	"	mov	x9, #(1 << 31)\n"	/* HCR_EL2.RW : EL1 en AArch64 */
	"	msr	hcr_el2, x9\n"
	"	msr	cptr_el2, xzr\n"
	"	mov	x9, #3\n"
	"	msr	cnthctl_el2, x9\n"
	"	msr	cntvoff_el2, xzr\n"
	"	movz	x9, #0x0800\n"
	"	movk	x9, #0x30d0, lsl #16\n"	/* SCTLR_EL1 RES1, MMU/caches coupés */
	"	msr	sctlr_el1, x9\n"
	"	adr	x9, 1f\n"
	"	msr	elr_el2, x9\n"
	"	mov	x9, #0x3c5\n"
	"	msr	spsr_el2, x9\n"
	"	isb\n"
	"	eret\n"
	"1:	ic	iallu\n"
	"	dsb	sy\n"
	"	isb\n"
	"	adr	x9, a73_boot_args\n"
	"	ldr	x0, [x9]\n"
	"	adr	x9, a73_entry_pa\n"
	"	ldr	x9, [x9]\n"
	"	mov	x1, xzr\n"
	"	mov	x2, xzr\n"
	"	mov	x3, xzr\n"
	"	br	x9\n"
);

/*
 * Trampoline des coeurs secondaires (au-dessus de 4 Go, l'entrée PSCI semble
 * tronquée) : XNU écrit son point d'entrée physique dans sec_target, puis
 * appelle CPU_ON avec l'adresse de sec_start (passée par a40sec= dans la ligne
 * de commande). Ce code reste en place : XNU n'utilise que la banque 0x880000000.
 */
__asm__(
	".text\n"
	".balign 64\n"
	"sec_start:\n"
	"	adr	x9, sec_target\n"
	"	ldr	x9, [x9]\n"
	"	br	x9\n"
	".balign 8\n"
	"sec_target:\n"
	"	.quad	0\n"
);

static int put_hex(volatile char *d, u64 v)
{
	int n = 0;
	d[n++] = '0';
	d[n++] = 'x';
	for (int s = 60; s >= 0; s -= 4) {
		int c = (v >> s) & 0xf;
		d[n++] = c < 10 ? '0' + c : 'a' + c - 10;
	}
	return n;
}

static u64 smc(u64 fn, u64 a1, u64 a2, u64 a3)
{
	register u64 x0 __asm__("x0") = fn;
	register u64 x1 __asm__("x1") = a1;
	register u64 x2 __asm__("x2") = a2;
	register u64 x3 __asm__("x3") = a3;
	__asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) :
	    : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15",
	    "x16", "x17", "memory");
	return x0;
}

static void kick(void)
{
	__asm__ volatile("dsb sy" ::: "memory");
	*(volatile u32 *)DECON_F_HW_SW_TRIG_CONTROL = EXYNOS_DECON_VALUE;
}

static void delay_ms(u64 ms)
{
	u64 f, t0, t;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(f));
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(t0));
	do {
		__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(t));
	} while (t - t0 < f / 1000 * ms);
}

#define PMU 0x11C80000UL
static inline u32 rd32(u64 a) { return *(volatile u32 *)a; }
static inline void wr32(u64 a, u32 v) { *(volatile u32 *)a = v; __asm__ volatile("dsb sy" ::: "memory"); }
static void rmw32(u64 a, u32 mask, u32 val) { wr32(a, (rd32(a) & ~mask) | (val & mask)); }

/* Séquences PMUCAL Exynos 7885 (pmucal_cpu_exynos7885.h) : cfg = CPUx_CONFIGURATION */
static void pmu_core_on(u64 shortstop, u64 seqopt, u64 cfg)
{
	if (shortstop)
		wr32(shortstop, 0xFFFFFFFF);
	if (seqopt) {
		rmw32(seqopt, 1u << 4, 1u << 4);
		rmw32(seqopt, 1u << 0, 0);
	}
	rmw32(cfg, 0xF, 0xF);
}

/* CPU_ON puis, si le PMU dit le coeur éteint, allumage PMU. Retourne 1 si alive == want. */
static int start_core(const char *name, u64 mpidr, u64 pc, u64 arg, u64 want,
    u64 shortstop, u64 seqopt, u64 cfg)
{
	a73_alive = 0;
	__asm__ volatile("dsb sy" ::: "memory");
	say_hex(name, mpidr, 3);
	say_hex(" PMU AVANT CFG/ST: ", ((u64)rd32(cfg) << 32) | rd32(cfg + 4), 16);
	u64 r = smc(PSCI_CPU_ON, mpidr, pc, arg);
	say_hex(" CPU_ON: ", r, 8);
	kick();
#if defined(PORT_BOARD_A10)
	/* Do not power-cycle a core after PSCI refused the entry request. */
	if (r != 0) return 0;
#endif
	for (int i = 0; i < 100 && a73_alive != want && !a73_feature_error; i++)
		delay_ms(5);
	say_hex(" APRES CPU_ON CFG/ST: ", ((u64)rd32(cfg) << 32) | rd32(cfg + 4), 16);
	if (a73_alive != want && !a73_feature_error) {
		pmu_core_on(shortstop, seqopt, cfg);
		for (int i = 0; i < 400 && a73_alive != want && !a73_feature_error; i++)
			delay_ms(5);
		say_hex(" APRES PMU CFG/ST: ", ((u64)rd32(cfg) << 32) | rd32(cfg + 4), 16);
	}
	say_hex(" ALIVE: ", a73_alive, 8);
	kick();
	return a73_alive == want;
}

static void fail(const char *why)
{
	say(why, C_ERR);
	kick();
	for (;;)
		__asm__ volatile("wfe");
}

__attribute__((used)) static void payload_main(const u8 *fdt, u64 base, u64 vectors_ok)
{
	(void)vectors_ok;
	display_ready = 0;
	loader_diagnostics.signature = 0x4c4d454d00000001UL;
	loader_diagnostics.stage = 1;
	loader_diagnostics.error = 0;
	loader_diagnostics.fdt_pa = (u64)fdt;
	loader_diagnostics.map_pa = (u64)&handoff_map;
	loader_diagnostics.image_pa = base;
	/* The boot protocol must provide readable header/tree memory. Bounds
	 * checks cannot turn an unmapped physical pointer into a valid one. */
	if (!fdt || (u64)fdt > UINT64_MAX - 40) early_stop(FM_HEADER);
	u32 fdt_size = fm_be32(fdt + 4);
	if (fdt_size < 40 || fdt_size > FM_MAX_DTB || fdt_size > UINT64_MAX - (u64)fdt)
		early_stop(FM_BOUNDS);
	int error = fm_parse(fdt, fdt_size, &handoff_map);
	if (error) early_stop((u32)error);
	loader_diagnostics.stage = 2;
	if (base > UINT64_MAX - 64) early_stop(0x200);
	u64 image_size = *(const u64 *)(base + 0x10);
	u64 blob_off = *(const u64 *)(base + 0x20), blob_size = *(const u64 *)(base + 0x28);
	loader_diagnostics.image_size = image_size;
	if (image_size < 64 || image_size > UINT64_MAX - base || blob_off < 64 || blob_off % 8 ||
	    blob_off > image_size || blob_size > image_size - blob_off) early_stop(0x200);
	const struct payload *p = (const struct payload *)(base + blob_off);
	struct pc_layout layout;
	error = pc_validate(p, blob_size, &layout);
	if (error) early_stop(0x100 + (u32)error);
	loader_diagnostics.stage = 3;
	struct fm_range protected[2] = {{base, image_size}, {(u64)fdt, fdt_size}};
	error = fm_check_window(&handoff_map, p->phys_base, p->mem_size, protected, 2);
	if (error) early_stop((u32)error);
	loader_diagnostics.stage = 4;
	/* Select the source-built profile explicitly; a model cannot switch a
	 * binary compiled for the other board into different hardware code. */
	error = exynos_check_board(&handoff_map);
	if (error) early_stop((u32)error);
	display_ready = 1;
	loader_diagnostics.stage = 5;
	fill(0, FB_H, C_BG);
	line = 0;
	say(EXYNOS_BOARD_LABEL, C_OK);

	say_hex("PHYS: ", p->phys_base, 9);
	say_hex("TAILLE PAYLOAD: ", blob_size, 8);
	kick();

	for (u32 i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		u64 dst = p->phys_base + (s->vmaddr - p->virt_base);
		copy64(dst, (u64)p + s->file_off, s->file_size);
		if (s->vmsize > s->file_size) {
			zero64(dst + s->file_size, s->vmsize - s->file_size);
		}
	}
	u64 adt_pa = layout.adt_pa;
	copy64(adt_pa, (u64)p + p->adt_off, p->adt_size);
	u64 ba_pa = layout.args_pa;
	u64 top = layout.top;
	zero64(ba_pa, PAGE_16K);
	volatile struct boot_args *ba = (volatile struct boot_args *)ba_pa;
	ba->revision = 2;
	ba->version = 2;
	ba->virt_base = p->virt_base;
	ba->phys_base = p->phys_base;
	ba->mem_size = p->mem_size;
	ba->top_of_kernel_data = top;
	ba->video.base = FB_BASE;
	ba->video.display = 1;
	ba->video.row_bytes = FB_W * 4;
	ba->video.width = FB_W;
	ba->video.height = FB_H;
	ba->video.depth = 32;
	ba->device_tree = p->kernel_end;		/* adresse virtuelle */
	ba->device_tree_length = (u32)p->adt_size;
	int cl = 0;
	for (; cl < BOOT_LINE_LENGTH - 1 && p->cmdline[cl]; cl++)
		ba->command_line[cl] = p->cmdline[cl];
	u64 sec_pc;
	__asm__ volatile("adr %0, sec_start" : "=r"(sec_pc));
	if (cl + 26 < BOOT_LINE_LENGTH) {
		const char *k = " a40sec=";
		for (int i = 0; k[i]; i++)
			ba->command_line[cl++] = k[i];
		cl += put_hex(ba->command_line + cl, sec_pc);
	}
	ba->command_line[cl] = 0;
	say_hex("SEC PC: ", sec_pc, 9);
	ba->mem_size_actual = p->mem_size;
	say_hex("BOOT_ARGS: ", ba_pa, 9);

	a73_entry_pa = layout.entry_pa;
	a73_boot_args = ba_pa;
	a73_alive = 0;
	a73_mmfr0 = 0;
	a73_feature_error = 0;
	say_hex("ENTREE XNU: ", a73_entry_pa, 9);
	__asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");

	u64 v = smc(PSCI_VERSION, 0, 0, 0);
	say_hex("PSCI: ", v, 8);
	say("CPU_ON A73 (MPIDR 0)...", C_DIM);
	kick();
	u64 a73_pc;
	__asm__ volatile("adr %0, a73_start" : "=r"(a73_pc));
	say_hex("A73 PC: ", a73_pc, 9);
#if EXYNOS_START_A53_WITNESS
	start_core("A53 TEMOIN ", 0x101, a73_pc, ba_pa, 0xA53, 0, 0, PMU + 0x2280);
#endif
	start_core("A73 ", A73_MPIDR, a73_pc, ba_pa, 0xA73, 0x10900820, PMU + 0x2488, PMU + 0x2000);
	if (a73_feature_error)
		fail("A73: GRANULE 16K OU EL INVALIDE");
	if (a73_alive != 0xA73)
		fail("A73: PAS DE SIGNE DE VIE");
	/* Le A73 efface l'écran en démarrant XNU : ne plus rien dessiner, s'éteindre. */
	smc(PSCI_CPU_OFF, 0, 0, 0);
	for (;;)
		__asm__ volatile("wfe");
}

__attribute__((used)) static void payload_fault(u64 vec, u64 esr, u64 elr, u64 far, u64 base)
{
	if (!display_ready) {
		loader_diagnostics.esr = esr;
		loader_diagnostics.far = far;
		early_stop(0x400);
	}
	fill(0, TOP + 7 * CELL_H, C_ERR);
	line = 0;
	say("EXCEPTION DANS LE LOADER", C_FG);
	say_hex("VECTEUR: ", vec, 2);
	say_hex("ESR: ", esr, 8);
	say_hex("ELR-BASE: ", elr - base, 6);
	say_hex("FAR: ", far, 9);
	kick();
}
