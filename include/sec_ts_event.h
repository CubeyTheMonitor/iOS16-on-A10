/* Samsung SEC 8-byte coordinate event wire decoder, no bus or power control.
 * Protocol reference: Eureka sec_incell_ts/sec_ts.h, sec_ts_event_coordinate.
 * Explicit shifts avoid compiler bitfield layout and alignment dependencies.
 * This is an offline building block, not an enabled A10 touchscreen driver.
 */
#pragma once
#include <stddef.h>
#include <stdint.h>

struct sec_ts_point {
	unsigned int slot, action, x, y, remaining;
};

/* 1 = coordinate; 0 = empty/non-coordinate; -1 = malformed coordinate/input.
 * Contact IDs are 1..10 on the wire. Returned slots are 0..9.
 * Actions: 1 press, 2 move, 3 release. Release coordinates may be stale.
 * Non-coordinate status/gesture packets require a separate future handler.
 * Output is untouched unless a valid coordinate is returned.
 */
static inline int sec_ts_decode(const uint8_t *p, size_t size,
    unsigned int width, unsigned int height, struct sec_ts_point *out)
{
	if (!p || !out || size != 8 || !width || !height)
		return -1;
	if ((p[0] & 3) != 0 || p[0] == 0)
		return 0;
	unsigned int id = (p[0] >> 2) & 15;
	unsigned int action = p[0] >> 6;
	unsigned int x = ((unsigned int)p[1] << 4) | (p[3] >> 4);
	unsigned int y = ((unsigned int)p[2] << 4) | (p[3] & 15);
	if (!id || id > 10 || !action ||
	    (action != 3 && (x >= width || y >= height)))
		return -1;
	*out = (struct sec_ts_point){id - 1, action, x, y, p[7] & 63};
	return 1;
}
