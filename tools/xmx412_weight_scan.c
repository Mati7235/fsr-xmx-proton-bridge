/* XMX 4.1.2 fsr-original.dll weight scanner (read-only, CPU-only).
 *
 * Reimplements the FUN_180049950 contract from docs/xmx412-model-selection.md
 * section 4.2. The target file is opened read-only and never executed; only
 * its bytes are inspected as data.
 *
 * Contract:
 *  1. Size must be >= 0x6B01.
 *  2. Scan 16-byte-aligned candidate offsets. At each candidate:
 *     a. 8 qwords at +0x440..+0x478 (64 bytes at +0x440) must be zero.
 *     b. In the first 0x200 little-endian UTF-16 words, indices 7,15,23,...
 *        (i.e. i%8==7) must be zero, and more than 400 words must be nonzero.
 *     c. FNV-1a64 over 0x6B00 bytes and over 0x20000 bytes from the same
 *        offset, compared against four constants:
 *          Lite preset   0x0CA02A3581DE817F (len 0x6B00, struct +0x38)
 *          Lite ultra    0x2DD74EE29ECB9705 (len 0x6B00, struct +0x50)
 *          INT8 preset   0x29CE14ECDF23D42B (len 0x20000, struct +0xD8)
 *          INT8 ultra    0x0DFCFD62036F9E391 (len 0x20000, struct +0xF0)
 *  3. Version marker: dword pairs [v, 0xF5A5CA1E] scanned 4-byte-aligned
 *     over the whole file; the largest positive (signed int32) v wins.
 *     major = v>>22, minor = (v>>12)&0x3FF, patch = v&0xFFF
 *     (4.1.2 packs as 0x01001002).
 *  4. Verdict: Lite OK iff both Lite blobs found and version != 0;
 *     INT8 OK iff both INT8 blobs found and version != 0.
 *
 * FNV-1a64 uses the standard offset basis 0xCBF29CE484222325 and prime
 * 0x100000001B3, hashed byte by byte (h ^= byte; h *= prime, mod 2^64).
 *
 * Performance: single pass. Cheap preconditions (a, b) run first over all
 * 16-aligned offsets; the expensive FNV hashes run only on candidates that
 * pass (a) and (b). A naive O(n*m) loop over the ~57 MB file had to be
 * killed; this completes in seconds with -O2.
 *
 * Usage: xmx412_weight_scan <path>
 * Exit status: 0 on a completed scan (even if verdict is FAIL), 1 on I/O
 * or usage errors.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SIZE_MIN 0x6B01u
#define ZERO_OFF 0x440u
#define ZERO_LEN 0x40u /* 8 qwords: +0x440..+0x478 inclusive */
#define WORDS_N 0x200u
#define WORDS_BYTES (WORDS_N * 2u)
#define LITE_LEN 0x6B00u
#define INT8_LEN 0x20000u
#define VERSION_MAGIC 0xF5A5CA1Eu
#define ALIGN 16u

#define FNV_BASIS 14695981039346656037ULL
#define FNV_PRIME 1099511628211ULL

#define LITE_PRESET_CONST 0x0CA02A3581DE817FULL
#define LITE_ULTRA_CONST 0x2DD74EE29ECB9705ULL
#define INT8_PRESET_CONST 0x29CE14ECDF23D42BULL
#define INT8_ULTRA_CONST 0x0DFCFD62036F9E391ULL

static uint64_t fnv1a64(const uint8_t *p, size_t n)
{
    uint64_t h = FNV_BASIS;
    size_t i;
    for (i = 0; i < n; i++) {
        h ^= (uint64_t)p[i];
        h *= FNV_PRIME;
    }
    return h;
}

static uint16_t rd_u16le(const uint8_t *p)
{
    uint16_t v;
    memcpy(&v, p, sizeof v);
    return v;
}

static uint32_t rd_u32le(const uint8_t *p)
{
    uint32_t v;
    memcpy(&v, p, sizeof v);
    return v;
}

static uint64_t rd_u64le(const uint8_t *p)
{
    uint64_t v;
    memcpy(&v, p, sizeof v);
    return v;
}

int main(int argc, char **argv)
{
    FILE *f;
    uint8_t *data;
    long fsize;
    size_t size, off;
    int32_t best_v = 0;
    size_t best_off = 0;
    int have_version = 0;
    unsigned long npairs = 0;
    unsigned long npref = 0;
    unsigned long nprint_pairs = 0, nprint_pref = 0;
    int lite_preset = 0, lite_ultra = 0, int8_preset = 0, int8_ultra = 0;
    size_t lite_preset_off = 0, lite_ultra_off = 0;
    size_t int8_preset_off = 0, int8_ultra_off = 0;
    int lite_ok, int8_ok;

    if (argc != 2) {
        fprintf(stderr, "usage: %s <dll-or-blob-path>\n", argv[0]);
        return 1;
    }
    f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "error: cannot open '%s'\n", argv[1]);
        return 1;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fprintf(stderr, "error: cannot seek '%s'\n", argv[1]);
        fclose(f);
        return 1;
    }
    fsize = ftell(f);
    if (fsize < 0) {
        fprintf(stderr, "error: cannot tell size of '%s'\n", argv[1]);
        fclose(f);
        return 1;
    }
    rewind(f);
    size = (size_t)fsize;
    data = (uint8_t *)malloc(size ? size : 1);
    if (!data) {
        fprintf(stderr, "error: out of memory for %lu bytes\n",
                (unsigned long)size);
        fclose(f);
        return 1;
    }
    if (size > 0 && fread(data, 1, size, f) != size) {
        fprintf(stderr, "error: short read on '%s'\n", argv[1]);
        free(data);
        fclose(f);
        return 1;
    }
    fclose(f);

    printf("file: %s\n", argv[1]);
    printf("size: %lu (0x%lx)\n", (unsigned long)size, (unsigned long)size);
    printf("size_ok: %s (need >= 0x%x)\n",
           size >= SIZE_MIN ? "yes" : "no", SIZE_MIN);

    /* 3. Version marker: dword pairs [v, magic], 4-byte aligned. */
    for (off = 0; off + 8 <= size; off += 4) {
        uint32_t v = rd_u32le(data + off);
        uint32_t m = rd_u32le(data + off + 4);
        int32_t sv;
        if (m != VERSION_MAGIC)
            continue;
        memcpy(&sv, &v, sizeof sv);
        if (sv <= 0)
            continue;
        npairs++;
        if (nprint_pairs < 64) {
            printf("version off=0x%lx v=0x%08x major=%u minor=%u patch=%u\n",
                   (unsigned long)off, v, v >> 22, (v >> 12) & 0x3FFu,
                   v & 0xFFFu);
            nprint_pairs++;
        }
        if (!have_version || sv > best_v) {
            have_version = 1;
            best_v = sv;
            best_off = off;
        }
    }
    if (npairs > nprint_pairs)
        printf("version ... %lu more pair(s) not shown\n",
               npairs - nprint_pairs);
    printf("version_pairs: %lu\n", npairs);
    if (have_version) {
        uint32_t bv = (uint32_t)best_v;
        printf("max_version: off=0x%lx v=0x%08x %u.%u.%u\n",
               (unsigned long)best_off, bv, bv >> 22, (bv >> 12) & 0x3FFu,
               bv & 0xFFFu);
    } else {
        printf("max_version: none\n");
    }

    if (size < SIZE_MIN) {
        printf("prefilter_hits: 0 (file too small, scan skipped)\n");
        printf("fnv_matches: 0\n");
        printf("verdict_lite: FAIL\n");
        printf("verdict_int8: FAIL\n");
        printf("overall: NONE\n");
        free(data);
        return 0;
    }

    /* 2. Candidate scan: 16-aligned offsets, cheap checks first. */
    for (off = 0; off + ZERO_OFF + ZERO_LEN <= size; off += ALIGN) {
        size_t k;
        int ok;
        unsigned long nonzero = 0;
        uint64_t h;

        if (off + WORDS_BYTES > size)
            break;

        /* (a) 8 qwords at +0x440 must be zero. */
        ok = 1;
        for (k = 0; k < 8; k++) {
            if (rd_u64le(data + off + ZERO_OFF + k * 8) != 0) {
                ok = 0;
                break;
            }
        }
        if (!ok)
            continue;

        /* (b) UTF-16 words: i%8==7 must be zero, >400 nonzero total. */
        for (k = 0; k < WORDS_N; k++) {
            uint16_t w = rd_u16le(data + off + k * 2);
            if ((k % 8) == 7) {
                if (w != 0) {
                    ok = 0;
                    break;
                }
            } else if (w != 0) {
                nonzero++;
            }
        }
        if (!ok || nonzero <= 400)
            continue;

        npref++;
        if (nprint_pref < 256) {
            printf("prefilter off=0x%lx nonzero_words=%lu\n",
                   (unsigned long)off, nonzero);
            nprint_pref++;
        }

        /* (c) FNV hashes only for survivors. */
        if (off + LITE_LEN <= size) {
            h = fnv1a64(data + off, LITE_LEN);
            if (h == LITE_PRESET_CONST) {
                lite_preset = 1;
                lite_preset_off = off;
                printf("fnv_match off=0x%lx len=0x%x const=0x%016llx "
                       "role=lite-preset dest=+0x38\n",
                       (unsigned long)off, LITE_LEN,
                       (unsigned long long)h);
            }
            if (h == LITE_ULTRA_CONST) {
                lite_ultra = 1;
                lite_ultra_off = off;
                printf("fnv_match off=0x%lx len=0x%x const=0x%016llx "
                       "role=lite-ultraperf dest=+0x50\n",
                       (unsigned long)off, LITE_LEN,
                       (unsigned long long)h);
            }
        }
        if (off + INT8_LEN <= size) {
            h = fnv1a64(data + off, INT8_LEN);
            if (h == INT8_PRESET_CONST) {
                int8_preset = 1;
                int8_preset_off = off;
                printf("fnv_match off=0x%lx len=0x%x const=0x%016llx "
                       "role=int8-preset dest=+0xD8\n",
                       (unsigned long)off, INT8_LEN,
                       (unsigned long long)h);
            }
            if (h == INT8_ULTRA_CONST) {
                int8_ultra = 1;
                int8_ultra_off = off;
                printf("fnv_match off=0x%lx len=0x%x const=0x%016llx "
                       "role=int8-ultraperf dest=+0xF0\n",
                       (unsigned long)off, INT8_LEN,
                       (unsigned long long)h);
            }
        }
    }
    if (npref > nprint_pref)
        printf("prefilter ... %lu more hit(s) not shown\n",
               npref - nprint_pref);
    printf("prefilter_hits: %lu\n", npref);
    printf("fnv_matches: %d\n",
           lite_preset + lite_ultra + int8_preset + int8_ultra);
    if (lite_preset)
        printf("lite_preset_off: 0x%lx\n", (unsigned long)lite_preset_off);
    if (lite_ultra)
        printf("lite_ultra_off: 0x%lx\n", (unsigned long)lite_ultra_off);
    if (int8_preset)
        printf("int8_preset_off: 0x%lx\n", (unsigned long)int8_preset_off);
    if (int8_ultra)
        printf("int8_ultra_off: 0x%lx\n", (unsigned long)int8_ultra_off);

    lite_ok = lite_preset && lite_ultra && have_version && best_v != 0;
    int8_ok = int8_preset && int8_ultra && have_version && best_v != 0;
    printf("verdict_lite: %s\n", lite_ok ? "OK" : "FAIL");
    printf("verdict_int8: %s\n", int8_ok ? "OK" : "FAIL");
    printf("overall: %s\n",
           lite_ok && int8_ok ? "LITE+INT8"
           : lite_ok ? "LITE"
           : int8_ok ? "INT8" : "NONE");

    free(data);
    return 0;
}
