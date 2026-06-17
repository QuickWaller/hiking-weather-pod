#pragma once
#include <stdint.h>

// ── Pod ML binary model format (v1) ──────────────────────────────────────────
//
// model.bin layout:
//
//   GLOBAL HEADER (28 bytes):
//     uint8_t  magic[4]     = {'P','O','M','L'}
//     uint16_t version      = 1
//     uint16_t n_outputs    = leaf output values per leaf
//     uint32_t n_trees      = total number of trees
//     uint32_t n_features   = number of input features
//     uint64_t schema_hash  = FNV-1a 64-bit of comma-joined feature names (in order)
//     uint32_t max_splits   = max n_splits in any tree (for buffer sizing)
//
//   PER TREE BLOCK (repeated n_trees times):
//     uint16_t n_splits     = number of split nodes in this tree
//     uint16_t n_leaves     = n_splits + 1
//
//     SPLIT NODES (n_splits × 10 bytes each):
//       uint16_t feature    = feature index (0-based)
//       float    threshold  = split threshold
//       int16_t  left       = >=0: split node index; <0: leaf index = -(v+1)
//       int16_t  right      = same convention
//
//     LEAF VALUES (n_leaves × n_outputs × 4 bytes):
//       float values[n_leaves][n_outputs]  (row-major)
//
// Tree traversal: start at split node 0, follow left/right until child < 0.
// Accumulate leaf_values[-(child+1)][*] into running sum across all trees.
// Final prediction = sum (gradient-boosted forest, no averaging).

static constexpr uint8_t  MODEL_MAGIC[4]  = {'P','O','M','L'};
static constexpr uint16_t MODEL_VERSION   = 1;
static constexpr uint8_t  MAX_MODEL_OUTPUTS = 20;   // max n_outputs supported
static constexpr uint16_t MAX_TREE_SPLITS   = 1023; // max n_splits per tree

// Feature names compiled into the firmware. These MUST match manifest.json
// features in order — the schema_hash is the guard. Update both together.
static constexpr uint8_t MODEL_N_FEATURES = 9;
static const char* const MODEL_FEATURE_NAMES[MODEL_N_FEATURES] = {
    "pressure_hpa",
    "temp_c",
    "humidity_pct",
    "pressure_rate_1h",
    "pressure_rate_3h",
    "hour_sin",
    "hour_cos",
    "doy_sin",
    "doy_cos",
};

// FNV-1a 64-bit of comma-joined MODEL_FEATURE_NAMES above.
// Recompute via: python3 -c "
//   names='pressure_hpa,temp_c,humidity_pct,pressure_rate_1h,pressure_rate_3h,hour_sin,hour_cos,doy_sin,doy_cos'
//   h=14695981039346656037; p=1099511628211
//   for c in names.encode(): h=((h^c)*p)&0xffffffffffffffff
//   print(hex(h))
// "
// Update this constant whenever MODEL_FEATURE_NAMES changes.
static constexpr uint64_t MODEL_SCHEMA_HASH = 0x0000000000000000ULL;  // placeholder — set after first export

#pragma pack(push, 1)
struct ModelHeader {
    uint8_t  magic[4];
    uint16_t version;
    uint16_t n_outputs;
    uint32_t n_trees;
    uint32_t n_features;
    uint64_t schema_hash;
    uint32_t max_splits;
};

struct ModelTreeHeader {
    uint16_t n_splits;
    uint16_t n_leaves;
};

struct ModelSplitNode {
    uint16_t feature;
    float    threshold;
    int16_t  left;   // >=0 = split index; <0 = leaf index = -(v+1)
    int16_t  right;
};
#pragma pack(pop)

static_assert(sizeof(ModelHeader)    == 28, "ModelHeader must be 28 bytes");
static_assert(sizeof(ModelSplitNode) == 10, "ModelSplitNode must be 10 bytes");
