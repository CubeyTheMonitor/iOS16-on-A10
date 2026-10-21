/* Bounded, allocation-free FDT v17 memory reader for pre-MMU boot code.
 * The caller must supply an accessible buffer; this cannot prove a physical
 * pointer is mapped. It never probes RAM or reads/writes peripheral registers.
 */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define FM_MAX_DTB (16u << 20)
#define FM_MAX_BANKS 16u
#define FM_MAX_RESERVED 128u
#define FM_MAX_DEPTH 32u

enum fm_error {
	FM_OK, FM_HEADER, FM_BOUNDS, FM_TREE, FM_UNSUPPORTED, FM_LIMIT,
	FM_OVERFLOW, FM_NO_RAM, FM_NOT_RAM, FM_RESERVED, FM_PROTECTED,
	FM_UNRESOLVED, FM_OVERLAY
};

struct fm_range { uint64_t start, size; };
struct fm_map {
	uint32_t valid, total_size, banks, reserved, zero_banks, unresolved;
	char model[96];
	struct fm_range bank[FM_MAX_BANKS], reserve[FM_MAX_RESERVED];
};

static uint32_t fm_be32(const unsigned char *p)
{
	return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static uint64_t fm_be64(const unsigned char *p)
{
	return (uint64_t)fm_be32(p) << 32 | fm_be32(p + 4);
}

static int fm_equal(const unsigned char *p, size_t n, const char *s)
{
	size_t i = 0;
	while (i < n && s[i] && p[i] == (unsigned char)s[i]) i++;
	return i == n && !s[i];
}

static int fm_prefix(const unsigned char *p, size_t n, const char *s)
{
	size_t i = 0;
	while (s[i]) {
		if (i == n || p[i] != (unsigned char)s[i]) return 0;
		i++;
	}
	return 1;
}

static void fm_clear(void *p, size_t n)
{
	volatile unsigned char *d = p;
	while (n--) *d++ = 0;
}

static int fm_overlap(uint64_t a, uint64_t size, uint64_t b, uint64_t other)
{
	/* Inputs have already passed non-overflow checks. */
	return size && other && a < b + other && b < a + size;
}

static int fm_add(struct fm_map *m, uint64_t start, uint64_t size, int bank)
{
	if (!size) {
		if (bank) m->zero_banks++;
		return FM_OK;
	}
	if (size > UINT64_MAX - start) return FM_OVERFLOW;
	uint32_t *count = bank ? &m->banks : &m->reserved;
	uint32_t max = bank ? FM_MAX_BANKS : FM_MAX_RESERVED;
	struct fm_range *r = bank ? m->bank : m->reserve;
	if (*count == max) return FM_LIMIT;
	if (bank) {
		for (uint32_t i = 0; i < *count; i++)
			if (fm_overlap(start, size, r[i].start, r[i].size)) return FM_TREE;
	}
	r[(*count)++] = (struct fm_range){start, size};
	return FM_OK;
}

struct fm_node {
	uint32_t ac, sc, parent_ac, parent_sc, seen, children;
	uint32_t root, memory, reserved_root, reserved_child, chosen, disabled;
	const unsigned char *reg;
	uint32_t reg_size, dynamic, ranges;
	uint64_t initrd_start, initrd_end;
};

static int fm_property(struct fm_node *n, struct fm_map *m,
    const unsigned char *key, size_t kn, const unsigned char *v, uint32_t len)
{
	unsigned int bit = 0;
	if (fm_equal(key, kn, "#address-cells")) bit = 1;
	else if (fm_equal(key, kn, "#size-cells")) bit = 2;
	else if (fm_equal(key, kn, "device_type")) bit = 4;
	else if (fm_equal(key, kn, "status")) bit = 8;
	else if (fm_equal(key, kn, "reg")) bit = 16;
	else if (fm_equal(key, kn, "size")) bit = 32;
	else if (fm_equal(key, kn, "ranges")) bit = 64;
	else if (fm_equal(key, kn, "model")) bit = 128;
	else if (fm_equal(key, kn, "linux,initrd-start")) bit = 256;
	else if (fm_equal(key, kn, "linux,initrd-end")) bit = 512;
	else if (fm_equal(key, kn, "linux,usable-memory") ||
	    fm_equal(key, kn, "linux,usable-memory-range")) return FM_UNSUPPORTED;
	if (!bit) return FM_OK;
	if (n->seen & bit) return FM_TREE;
	n->seen |= bit;
	if (bit <= 2) {
		if (len != 4) return FM_TREE;
		uint32_t cells = fm_be32(v);
		/* Unrelated buses may have e.g. three PCI address cells. */
		if (bit == 1) n->ac = cells; else n->sc = cells;
	} else if (bit == 4) {
		if (!len || v[len - 1]) return FM_TREE;
		if (n->memory && !fm_equal(v, len - 1, "memory")) return FM_TREE;
		if (fm_equal(v, len - 1, "memory")) n->memory |= 2;
	} else if (bit == 8) {
		if (!len || v[len - 1]) return FM_TREE;
		n->disabled |= !(fm_equal(v, len - 1, "okay") || fm_equal(v, len - 1, "ok"));
	} else if (bit == 16) {
		n->reg = v; n->reg_size = len;
	} else if (bit == 32) {
		if (n->reserved_child && (!n->parent_sc || n->parent_sc > 2 || len != n->parent_sc * 4)) return FM_TREE;
		n->dynamic = 1;
	} else if (bit == 64) {
		if (n->reserved_root && len) return FM_UNSUPPORTED;
		n->ranges = 1;
	} else if (bit == 128 && n->root) {
		if (!len || len > sizeof(m->model) || v[len - 1]) return FM_TREE;
		for (uint32_t i = 0; i < len; i++) m->model[i] = (char)v[i];
	} else if (bit >= 256 && n->chosen) {
		if (len != 4 && len != 8) return FM_TREE;
		uint64_t value = len == 4 ? fm_be32(v) : fm_be64(v);
		if (bit == 256) n->initrd_start = value; else n->initrd_end = value;
	}
	return FM_OK;
}

static int fm_finish(struct fm_node *n, struct fm_map *m)
{
	if (n->reserved_root && !n->ranges) return FM_UNSUPPORTED;
	if ((n->reserved_child || n->memory) && n->children) return FM_UNSUPPORTED;
	if (n->chosen && (n->seen & (256 | 512))) {
		if ((n->seen & (256 | 512)) != (256 | 512) || n->initrd_end < n->initrd_start) return FM_TREE;
		int e = fm_add(m, n->initrd_start, n->initrd_end - n->initrd_start, 0);
		if (e) return e;
	}
	if (!n->memory && !n->reserved_child) return FM_OK;
	if (n->memory && n->disabled) return FM_OK;
	if (!n->reg) {
		if (n->reserved_child) { m->unresolved++; return FM_OK; }
		return FM_TREE;
	}
	if (n->parent_ac < 1 || n->parent_ac > 2 || n->parent_sc < 1 || n->parent_sc > 2) return FM_UNSUPPORTED;
	uint32_t stride = (n->parent_ac + n->parent_sc) * 4;
	if (!n->reg_size || n->reg_size % stride) return FM_TREE;
	for (uint32_t i = 0; i < n->reg_size; i += stride) {
		uint64_t start = n->parent_ac == 1 ? fm_be32(n->reg + i) : fm_be64(n->reg + i);
		const unsigned char *p = n->reg + i + n->parent_ac * 4;
		uint64_t size = n->parent_sc == 1 ? fm_be32(p) : fm_be64(p);
		/* A zero-sized reserved tuple may be a firmware placeholder. */
		if (!size && n->reserved_child) m->unresolved++;
		int e = fm_add(m, start, size, n->memory != 0);
		if (e) return e;
	}
	return FM_OK;
}

static int fm_parse(const void *buffer, size_t available, struct fm_map *m)
{
	if (!m) return FM_HEADER;
	fm_clear(m, sizeof(*m));
	if (!buffer || available < 40) return FM_HEADER;
	const unsigned char *b = buffer;
	uint32_t total = fm_be32(b + 4), so = fm_be32(b + 8), strings = fm_be32(b + 12);
	uint32_t reserve = fm_be32(b + 16), ns = fm_be32(b + 32), ss = fm_be32(b + 36);
	if (fm_be32(b) != 0xd00dfeed || fm_be32(b + 20) != 17 ||
	    (fm_be32(b + 24) != 16 && fm_be32(b + 24) != 17)) return FM_HEADER;
	if (total < 40 || total > available || total > FM_MAX_DTB || so < 40 || strings < 40 || reserve < 40 ||
	    so > total || ss > total - so || strings > total || ns > total - strings ||
	    reserve > total || so % 4 || ss % 4 || ss < 12 || reserve % 8 ||
	    fm_overlap(so, ss, strings, ns)) return FM_BOUNDS;
	m->total_size = total;
	uint32_t pos = reserve;
	for (;;) {
		if (total - pos < 16 || fm_overlap(pos, 16, so, ss) || fm_overlap(pos, 16, strings, ns)) return FM_BOUNDS;
		uint64_t start = fm_be64(b + pos), size = fm_be64(b + pos + 8);
		pos += 16;
		if (!start && !size) break;
		if (!size) return FM_TREE;
		int e = fm_add(m, start, size, 0);
		if (e) return e;
	}
	struct fm_node stack[FM_MAX_DEPTH];
	uint32_t depth = 0, roots = 0;
	pos = so;
	while (pos < so + ss) {
		uint32_t token = fm_be32(b + pos); pos += 4;
		if (token == 1) {
			uint32_t start = pos;
			while (pos < so + ss && b[pos]) {
				if (b[pos] == '/') return FM_TREE;
				pos++;
			}
			if (pos == so + ss || pos - start > 1024 || depth == FM_MAX_DEPTH) return FM_LIMIT;
			uint32_t len = pos - start;
			pos = (pos + 4) & ~3u;
			if (pos > so + ss || (!depth && (len || roots++)) || (depth && !len)) return FM_TREE;
			if (depth == 1 && (fm_prefix(b + start, len, "fragment@") ||
			    fm_equal(b + start, len, "__fixups__") || fm_equal(b + start, len, "__local_fixups__"))) return FM_OVERLAY;
			struct fm_node *n = &stack[depth];
			fm_clear(n, sizeof(*n));
			n->ac = 2; n->sc = 1; n->root = depth == 0;
			if (depth) {
				struct fm_node *parent = &stack[depth - 1];
				parent->children = 1;
				n->parent_ac = parent->ac; n->parent_sc = parent->sc;
				n->disabled = parent->disabled;
				n->reserved_child = parent->reserved_root;
			}
			if (depth == 1) {
				n->memory = fm_equal(b + start, len, "memory") || fm_prefix(b + start, len, "memory@");
				n->reserved_root = fm_equal(b + start, len, "reserved-memory");
				n->chosen = fm_equal(b + start, len, "chosen") || fm_equal(b + start, len, "chosen@0");
			}
			depth++;
		} else if (token == 2) {
			if (!depth) return FM_TREE;
			struct fm_node *n = &stack[--depth];
			/* Only root memory nodes describe physical DRAM. */
			if (depth != 1) n->memory = 0;
			int e = fm_finish(n, m);
			if (e) return e;
		} else if (token == 3) {
			if (!depth || so + ss - pos < 8 || stack[depth - 1].children) return FM_TREE;
			uint32_t len = fm_be32(b + pos), no = fm_be32(b + pos + 4); pos += 8;
			if (len > so + ss - pos || no >= ns) return FM_BOUNDS;
			uint32_t end = no;
			while (end < ns && b[strings + end]) end++;
			if (end == ns || end == no) return FM_TREE;
			int e = fm_property(&stack[depth - 1], m, b + strings + no, end - no, b + pos, len);
			if (e) return e;
			pos = (pos + len + 3) & ~3u;
			if (pos > so + ss) return FM_BOUNDS;
		} else if (token == 4) {
			continue;
		} else if (token == 9) {
			if (depth || roots != 1) return FM_TREE;
			while (pos < so + ss) if (b[pos++]) return FM_TREE;
			if (!m->banks) return FM_NO_RAM;
			m->valid = 1;
			return FM_OK;
		} else return FM_TREE;
	}
	return FM_TREE;
}

/* The entire kernel-managed window must fit one bank. No automatic allocation,
 * joining of banks, exclusion guesses, or acceptance of unresolved pools.
 */
static int fm_check_window(const struct fm_map *m, uint64_t start, uint64_t size,
    const struct fm_range *protected, size_t count)
{
	if (!m || !m->valid || !size || (count && !protected)) return FM_TREE;
	if (size > UINT64_MAX - start) return FM_OVERFLOW;
	int found = 0;
	for (uint32_t i = 0; i < m->banks; i++) {
		const struct fm_range *r = &m->bank[i];
		if (start >= r->start && start - r->start < r->size && size <= r->size - (start - r->start)) found = 1;
	}
	if (!found) return FM_NOT_RAM;
	for (uint32_t i = 0; i < m->reserved; i++)
		if (fm_overlap(start, size, m->reserve[i].start, m->reserve[i].size)) return FM_RESERVED;
	for (size_t i = 0; i < count; i++) {
		if (protected[i].size > UINT64_MAX - protected[i].start) return FM_OVERFLOW;
		if (fm_overlap(start, size, protected[i].start, protected[i].size)) return FM_PROTECTED;
	}
	return m->unresolved ? FM_UNRESOLVED : FM_OK;
}
