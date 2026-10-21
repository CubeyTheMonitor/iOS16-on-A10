/* Exact-length transfers for aligned bare-metal buffers. No MMIO access.
 * The including file supplies u8/u64. Both copy buffers must be 8-aligned.
 */
#pragma once

static void copy64(u64 dst, u64 src, u64 n)
{
	volatile u64 *d = (volatile u64 *)dst;
	const volatile u64 *s = (const volatile u64 *)src;
	for (u64 i = 0; i < n / 8; i++)
		d[i] = s[i];
	for (u64 i = n & ~7UL; i < n; i++)
		((volatile u8 *)dst)[i] = ((const volatile u8 *)src)[i];
}

/* Byte stores also allow a BSS tail starting at a non-word-aligned file end. */
static void zero64(u64 dst, u64 n)
{
	volatile u8 *d = (volatile u8 *)dst;
	while (n && (dst & 7)) {
		*d++ = 0;
		dst++;
		n--;
	}
	volatile u64 *q = (volatile u64 *)d;
	for (u64 i = 0; i < n / 8; i++)
		q[i] = 0;
	d += n & ~7UL;
	for (u64 i = 0; i < (n & 7); i++)
		d[i] = 0;
}
