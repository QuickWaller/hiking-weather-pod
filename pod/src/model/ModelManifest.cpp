#include "ModelManifest.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>

// ── FNV-1a 64-bit ─────────────────────────────────────────────────────────────

uint64_t ModelManifest::computeSchemaHash(const char* const* names, uint8_t n) {
    uint64_t h = 14695981039346656037ULL;
    const uint64_t prime = 1099511628211ULL;
    for (uint8_t i = 0; i < n; i++) {
        if (i > 0) {
            h ^= (uint8_t)',';
            h *= prime;
        }
        for (const char* p = names[i]; *p; p++) {
            h ^= (uint8_t)*p;
            h *= prime;
        }
    }
    return h;
}

// ── Minimal JSON field extractor ───────────────────────────────────────────────

static const char* findKey(const char* json, const char* key) {
    char pattern[MAX_FEATURE_NAME_LEN + 4];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char* p = strstr(json, pattern);
    if (!p) return nullptr;
    p += strlen(pattern);
    while (*p == ' ' || *p == '\t') p++;
    if (*p != ':') return nullptr;
    p++;
    while (*p == ' ' || *p == '\t') p++;
    return p;
}

static int parseIntAt(const char* p, int defaultVal) {
    if (!p) return defaultVal;
    return (int)strtol(p, nullptr, 10);
}

static bool parseStringAt(const char* p, char* buf, size_t len) {
    if (!p || *p != '"') return false;
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i < len - 1) buf[i++] = *p++;
    buf[i] = '\0';
    return true;
}

static uint64_t parseHexAt(const char* p) {
    if (!p || *p != '"') return 0;
    p++;
    return (uint64_t)strtoull(p, nullptr, 16);
}

// ── JSON parse ────────────────────────────────────────────────────────────────

bool ModelManifest::parseJson(const char* json, ModelManifest& dest) {
    memset(&dest, 0, sizeof(dest));

    const char* p;

    p = findKey(json, "version");
    dest.version = p ? (uint16_t)parseIntAt(p, 0) : 0;

    p = findKey(json, "trained_at");
    parseStringAt(p, dest.trained_at, sizeof(dest.trained_at));

    p = findKey(json, "model_file");
    parseStringAt(p, dest.model_file, sizeof(dest.model_file));

    p = findKey(json, "n_features");
    dest.n_features = p ? (uint8_t)parseIntAt(p, 0) : 0;

    p = findKey(json, "n_outputs");
    dest.n_outputs = p ? (uint8_t)parseIntAt(p, 0) : 0;

    p = findKey(json, "schema_hash");
    dest.schema_hash = parseHexAt(p);

    // Parse features array
    p = findKey(json, "features");
    if (p && *p == '[') {
        p++;
        uint8_t count = 0;
        while (*p && *p != ']' && count < MAX_MANIFEST_FEATURES) {
            while (*p == ' ' || *p == '\n' || *p == '\r' || *p == ',') p++;
            if (*p == '"') {
                p++;
                size_t i = 0;
                while (*p && *p != '"' && i < MAX_FEATURE_NAME_LEN - 1)
                    dest.features[count][i++] = *p++;
                dest.features[count][i] = '\0';
                if (*p == '"') p++;
                count++;
            } else if (*p == ']') {
                break;
            } else {
                p++;
            }
        }
    }

    // Parse output_names array
    p = findKey(json, "output_names");
    if (p && *p == '[') {
        p++;
        uint8_t count = 0;
        while (*p && *p != ']' && count < MAX_MANIFEST_OUTPUTS) {
            while (*p == ' ' || *p == '\n' || *p == '\r' || *p == ',') p++;
            if (*p == '"') {
                p++;
                size_t i = 0;
                while (*p && *p != '"' && i < MAX_OUTPUT_NAME_LEN - 1)
                    dest.output_names[count][i++] = *p++;
                dest.output_names[count][i] = '\0';
                if (*p == '"') p++;
                count++;
            } else if (*p == ']') {
                break;
            } else {
                p++;
            }
        }
    }

    dest.valid = (dest.version > 0 && dest.n_features > 0 && dest.n_outputs > 0);
    return dest.valid;
}

// ── Platform file loading ─────────────────────────────────────────────────────

#ifdef NATIVE_TEST

#include <stdio.h>

bool ModelManifest::loadFromFile(const char* path, ModelManifest& dest) {
    FILE* f = fopen(path, "r");
    if (!f) return false;

    char buf[1024] = {0};
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = '\0';

    return parseJson(buf, dest);
}

#else  // embedded

#include <SD.h>

bool ModelManifest::loadFromSd(const char* path, ModelManifest& dest) {
    File f = SD.open(path, FILE_READ);
    if (!f) return false;

    char buf[1024] = {0};
    size_t n = 0;
    while (f.available() && n < sizeof(buf) - 1)
        buf[n++] = f.read();
    f.close();
    buf[n] = '\0';

    return parseJson(buf, dest);
}

#endif
