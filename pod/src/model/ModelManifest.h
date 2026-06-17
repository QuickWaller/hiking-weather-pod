#pragma once
#include <stdint.h>

static constexpr uint8_t MAX_MANIFEST_FEATURES   = 32;
static constexpr uint8_t MAX_FEATURE_NAME_LEN     = 32;
static constexpr uint8_t MAX_MANIFEST_OUTPUTS     = 20;
static constexpr uint8_t MAX_OUTPUT_NAME_LEN      = 32;

struct ModelManifest {
    uint16_t version;
    char     trained_at[24];
    char     model_file[32];
    uint8_t  n_features;
    char     features[MAX_MANIFEST_FEATURES][MAX_FEATURE_NAME_LEN];
    uint64_t schema_hash;
    uint8_t  n_outputs;
    char     output_names[MAX_MANIFEST_OUTPUTS][MAX_OUTPUT_NAME_LEN];
    bool     valid;

    // Compute FNV-1a 64-bit hash of comma-joined feature names (in order).
    // Used both by the firmware to validate the manifest and by the offline
    // exporter to produce the hash that goes into manifest.json.
    static uint64_t computeSchemaHash(const char* const* names, uint8_t n);

    // Parse manifest.json from a null-terminated JSON string into dest.
    // Returns true if all required fields were found.
    static bool parseJson(const char* json, ModelManifest& dest);

#ifndef NATIVE_TEST
    // Load manifest.json from SD card path into dest.
    // Returns true on success.
    static bool loadFromSd(const char* path, ModelManifest& dest);
#else
    // Load manifest.json from a file path (native / test builds).
    static bool loadFromFile(const char* path, ModelManifest& dest);
#endif
};
