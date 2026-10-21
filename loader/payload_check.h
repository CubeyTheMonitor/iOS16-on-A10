/* Runtime SWEETXNU v1 layout checks, before any payload-directed writes. */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define BOOT_LINE_LENGTH 608
#define PAGE_16K 0x4000UL
#define PC_MAX_SEGS 128u

struct payload_seg { uint64_t vmaddr, vmsize, file_off, file_size; };
struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};
struct pc_layout { uint64_t adt_pa, args_pa, top, entry_pa; };
enum pc_error { PC_OK, PC_HEADER, PC_RANGE, PC_OVERLAP, PC_ENTRY, PC_CMDLINE };

static int pc_overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{
	return n && m && a < b + m && b < a + n;
}

static int pc_validate(const struct payload *p, uint64_t bytes, struct pc_layout *layout)
{
	if (!p || !layout || bytes < sizeof(*p)) return PC_HEADER;
	const char magic[8] = {'S','W','E','E','T','X','N','U'};
	for (unsigned int i = 0; i < 8; i++) if (p->magic[i] != magic[i]) return PC_HEADER;
	if (p->version != 1 || !p->nsegs || p->nsegs > PC_MAX_SEGS ||
	    p->nsegs > (bytes - sizeof(*p)) / sizeof(p->segs[0])) return PC_HEADER;
	uint64_t table_end = sizeof(*p) + p->nsegs * sizeof(p->segs[0]);
	if (!p->mem_size || p->phys_base % PAGE_16K || p->mem_size % PAGE_16K ||
	    p->virt_base % PAGE_16K || p->kernel_end % PAGE_16K ||
	    p->mem_size > UINT64_MAX - p->phys_base || p->mem_size > UINT64_MAX - p->virt_base ||
	    p->kernel_end <= p->virt_base || p->kernel_end - p->virt_base >= p->mem_size) return PC_RANGE;
	if (!p->adt_size || p->adt_size > UINT32_MAX || p->adt_off % 8 || p->adt_off < table_end ||
	    p->adt_off > bytes || p->adt_size > bytes - p->adt_off) return PC_RANGE;
	uint64_t offset = p->kernel_end - p->virt_base;
	if (p->adt_size > p->mem_size - offset) return PC_RANGE;
	uint64_t end = offset + p->adt_size;
	if (end > UINT64_MAX - (PAGE_16K - 1)) return PC_RANGE;
	uint64_t args = (end + PAGE_16K - 1) & ~(PAGE_16K - 1);
	if (args > p->mem_size || PAGE_16K > p->mem_size - args) return PC_RANGE;
	unsigned int cl = 0;
	while (cl < BOOT_LINE_LENGTH && p->cmdline[cl]) cl++;
	if (cl + 26 >= BOOT_LINE_LENGTH) return PC_CMDLINE;
	int entry_found = 0;
	for (uint32_t i = 0; i < p->nsegs; i++) {
		const struct payload_seg *s = &p->segs[i];
		if (!s->vmsize || s->vmaddr % 8 || s->vmaddr < p->virt_base ||
		    s->vmaddr > p->kernel_end || s->vmsize > p->kernel_end - s->vmaddr ||
		    s->file_size > s->vmsize || s->file_off % 8 || s->file_off < table_end ||
		    s->file_off > bytes || s->file_size > bytes - s->file_off) return PC_RANGE;
		if (pc_overlap(s->file_off, s->file_size, p->adt_off, p->adt_size)) return PC_OVERLAP;
		if (p->entry_va >= s->vmaddr && p->entry_va - s->vmaddr < s->file_size) entry_found = 1;
		for (uint32_t j = 0; j < i; j++) {
			const struct payload_seg *q = &p->segs[j];
			if (pc_overlap(s->vmaddr, s->vmsize, q->vmaddr, q->vmsize) ||
			    pc_overlap(s->file_off, s->file_size, q->file_off, q->file_size)) return PC_OVERLAP;
		}
	}
	if (!entry_found || p->entry_va % 4) return PC_ENTRY;
	layout->adt_pa = p->phys_base + offset;
	layout->args_pa = p->phys_base + args;
	layout->top = layout->args_pa + PAGE_16K;
	layout->entry_pa = p->phys_base + (p->entry_va - p->virt_base);
	return PC_OK;
}
