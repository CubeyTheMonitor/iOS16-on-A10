#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned char u8;
typedef unsigned long u64;
#include "../loader/memory.h"
#include "../include/sec_ts_event.h"

static void test_memory(void)
{
	_Alignas(8) u8 dst[96];
	for (unsigned int n = 1; n <= 65; n++) {
		/* Heap redzones let ASan detect even a read past a short source. */
		u8 *src = malloc(n);
		assert(src);
		memset(src, 0x37, n);
		memset(dst, 0xa5, sizeof(dst));
		copy64((u64)dst, (u64)src, n);
		assert(!memcmp(src, dst, n));
		assert(dst[n] == 0xa5);
		free(src);
	}
	for (unsigned int off = 0; off < 8; off++)
		for (unsigned int n = 0; n <= 65; n++) {
			memset(dst, 0xa5, sizeof(dst));
			zero64((u64)(dst + off), n);
			for (unsigned int i = 0; i < sizeof(dst); i++)
				assert(dst[i] == (i >= off && i < off+n ? 0 : 0xa5));
		}
}

static void test_sec(void)
{
	struct sec_ts_point out = {99, 99, 99, 99, 99};
	/* Press contact 1 at x=719, y=1519; low nibbles share byte 3. */
	u8 p[8] = {0x44, 0x2c, 0x5e, 0xff, 12, 8, 17, 0x42};
	assert(sec_ts_decode(p, 8, 720, 1520, &out) == 1);
	assert(out.slot == 0 && out.action == 1 && out.x == 719 && out.y == 1519 && out.remaining == 2);
	p[0] = 0xa8; /* Move contact 10. */
	assert(sec_ts_decode(p, 8, 720, 1520, &out) == 1 && out.slot == 9 && out.action == 2);
	p[1] = 0xff;
	assert(sec_ts_decode(p, 8, 720, 1520, &out) == -1);
	p[0] = 0xe8; /* Releases must work with stale out-of-range coordinates. */
	assert(sec_ts_decode(p, 8, 720, 1520, &out) == 1 && out.action == 3);
	for (unsigned int first = 0; first < 256; first++) {
		p[0] = (u8)first;
		p[1] = p[2] = p[3] = 0;
		unsigned int id = (first >> 2) & 15, action = first >> 6;
		int expected = (first & 3) || !first ? 0 : (!id || id > 10 || !action ? -1 : 1);
		struct sec_ts_point before = out;
		assert(sec_ts_decode(p, 8, 720, 1520, &out) == expected);
		if (expected != 1)
			assert(!memcmp(&before, &out, sizeof(out)));
	}
	assert(sec_ts_decode(p, 7, 720, 1520, &out) == -1);
	assert(sec_ts_decode(p, 9, 720, 1520, &out) == -1);
	assert(sec_ts_decode(NULL, 8, 720, 1520, &out) == -1);
	assert(sec_ts_decode(p, 8, 0, 1520, &out) == -1);
	assert(sec_ts_decode(p, 8, 720, 1520, NULL) == -1);
}

int main(void)
{
	test_memory();
	test_sec();
	puts("portable memory and SEC event tests passed");
	return 0;
}
