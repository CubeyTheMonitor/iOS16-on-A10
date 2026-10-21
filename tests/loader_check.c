/* Host adapter: feeds heap-bounded fixtures into the exact runtime validators. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../loader/fdt_memory.h"
#include "../loader/payload_check.h"

int main(int argc, char **argv)
{
    if (argc < 3) return 2;
    FILE *f = fopen(argv[2], "rb");
    if (!f || fseek(f, 0, SEEK_END)) return 2;
    long length = ftell(f);
    if (length < 0 || length > FM_MAX_DTB || fseek(f, 0, SEEK_SET)) return 2;
    unsigned char *data = malloc(length ? (size_t)length : 1);
    if (!data || fread(data, 1, (size_t)length, f) != (size_t)length) return 2;
    fclose(f);
    if (!strcmp(argv[1], "fdt")) {
        struct fm_map map;
        int error = fm_parse(data, (size_t)length, &map), window = -1;
        struct fm_range protect[2];
        if (argc != 3 && argc != 5 && argc != 7 && argc != 9) return 2;
        if (!error && argc >= 5) {
            for (int i = 5; i < argc; i += 2)
                protect[(i - 5) / 2] = (struct fm_range){strtoull(argv[i], NULL, 0), strtoull(argv[i+1], NULL, 0)};
            window = fm_check_window(&map, strtoull(argv[3], NULL, 0),
                strtoull(argv[4], NULL, 0), protect, (size_t)(argc - 5) / 2);
        }
        printf("{\"error\":%d,\"valid\":%u,\"banks\":%u,\"reserved\":%u,\"zero\":%u,\"unresolved\":%u,\"window\":%d}\n",
            error, map.valid, map.banks, map.reserved, map.zero_banks, map.unresolved, window);
    } else if (!strcmp(argv[1], "payload")) {
        struct pc_layout layout = {0};
        int error = pc_validate((const struct payload *)data, (uint64_t)length, &layout);
        printf("{\"error\":%d,\"adt\":%llu,\"args\":%llu,\"top\":%llu,\"entry\":%llu}\n",
            error, (unsigned long long)layout.adt_pa, (unsigned long long)layout.args_pa,
            (unsigned long long)layout.top, (unsigned long long)layout.entry_pa);
    } else return 2;
    free(data);
    return 0;
}
