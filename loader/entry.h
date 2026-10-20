/*
 * Entrée commune : en-tête Image arm64, pile, vecteurs d'exception.
 * Le programme définit payload_main(dtb, base, vecteurs_ok) et payload_fault(vec, esr, elr, far, base).
 * Les champs 0x20/0x28 de l'en-tête (réservés pour Linux) sont remplis par pack.py : offset et taille du blob ajouté ;
 * 0x30 (res4) et 0x3C (res5, u32) : offset et taille du ramdisk optionnel.
 */
#pragma once

/* Entrée : en-tête Image arm64 (certains bootloaders le vérifient), pile, vecteurs. */
__asm__(
	".text\n"
	"_head:\n"
	"	b	_start\n"
	"	.long	0\n"
	"	.quad	0\n"			/* text_offset */
	"	.quad	0\n"			/* image_size, rempli par pack.py */
	"	.quad	0xA\n"			/* little endian, pages 4K, chargeable partout */
	"	.quad	0, 0, 0\n"
	"	.ascii	\"ARM\\x64\"\n"
	"	.long	0\n"
	"_start:\n"
	"	mov	x19, x0\n"		/* DTB passé par S-Boot */
	"	adr	x20, _head\n"		/* adresse où on a été chargé */
	"	adr	x1, stack_top\n"
	"	mov	sp, x1\n"
	"	mov	x21, #0\n"		/* 1 = vecteurs installés */
	"	adr	x3, vectors\n"
	"	tst	x3, #0x7ff\n"
	"	b.ne	3f\n"
	"	mov	x21, #1\n"
	"	mrs	x2, CurrentEL\n"
	"	ubfx	x2, x2, #2, #2\n"
	"	cmp	x2, #2\n"
	"	b.eq	1f\n"
	"	cmp	x2, #3\n"
	"	b.eq	2f\n"
	"	msr	vbar_el1, x3\n"
	"	b	3f\n"
	"1:	msr	vbar_el2, x3\n"
	"	b	3f\n"
	"2:	msr	vbar_el3, x3\n"
	"3:	isb\n"
	"	mov	x0, x19\n"
	"	mov	x1, x20\n"
	"	mov	x2, x21\n"
	"	bl	payload_main\n"
	"4:	wfe\n"
	"	b	4b\n"

	".balign 2048\n"
	"vectors:\n"
	".irp i, 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15\n"
	"	.balign 128\n"
	"	mov	x0, #\\i\n"
	"	b	exc_common\n"
	".endr\n"
	"exc_common:\n"
	"	adr	x9, stack_top\n"
	"	mov	sp, x9\n"
	"	mrs	x9, CurrentEL\n"
	"	ubfx	x9, x9, #2, #2\n"
	"	cmp	x9, #2\n"
	"	b.eq	1f\n"
	"	cmp	x9, #3\n"
	"	b.eq	2f\n"
	"	mrs	x1, esr_el1\n"
	"	mrs	x2, elr_el1\n"
	"	mrs	x3, far_el1\n"
	"	b	3f\n"
	"1:	mrs	x1, esr_el2\n"
	"	mrs	x2, elr_el2\n"
	"	mrs	x3, far_el2\n"
	"	b	3f\n"
	"2:	mrs	x1, esr_el3\n"
	"	mrs	x2, elr_el3\n"
	"	mrs	x3, far_el3\n"
	"3:	adr	x4, _head\n"
	"	bl	payload_fault\n"
	"4:	wfe\n"
	"	b	4b\n"
);

__asm__(
	".text\n"
	".balign 16\n"
	"stack_bottom:\n"
	"	.zero	32768\n"
	"stack_top:\n"
);
