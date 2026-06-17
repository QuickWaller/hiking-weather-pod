#include "ModelEvaluator.h"
#include <string.h>
#include <stdlib.h>

// ── Core tree traversal (platform-independent) ────────────────────────────────

void ModelEvaluator::accumulateTree(
        const ModelSplitNode* splits,   uint16_t n_splits,
        const float*          leaf_vals, uint16_t n_leaves,
        const float*          features,  uint8_t  n_features,
        float*                acc,       uint8_t  n_outputs) {
    (void)n_leaves;

    int16_t node = 0;  // start at root split node
    for (;;) {
        if (node < 0 || (uint16_t)node >= n_splits) break;  // safety
        const ModelSplitNode& s = splits[node];
        float fval = (s.feature < n_features) ? features[s.feature] : 0.0f;
        int16_t child = (fval <= s.threshold) ? s.left : s.right;
        if (child < 0) {
            // Leaf: child = -(leaf_idx + 1)
            uint16_t leaf = (uint16_t)(-(child + 1));
            const float* lv = leaf_vals + (size_t)leaf * n_outputs;
            for (uint8_t i = 0; i < n_outputs; i++) acc[i] += lv[i];
            break;
        }
        node = child;
    }
}

// ── Platform file I/O ─────────────────────────────────────────────────────────

#ifdef NATIVE_TEST
#include <stdio.h>

static bool readBytes(FILE* f, void* buf, size_t n) {
    return fread(buf, 1, n, f) == n;
}

bool ModelEvaluator::begin(const char* manifest_path, const char* model_path) {
    ready_ = false; schemaOk_ = false;
    if (!ModelManifest::loadFromFile(manifest_path, manifest_)) return false;
    schemaOk_ = (manifest_.schema_hash == MODEL_SCHEMA_HASH) || (MODEL_SCHEMA_HASH == 0);
    strncpy(modelPath_, model_path, sizeof(modelPath_) - 1);
    ready_ = true;
    return true;
}

ModelEvaluator::Result ModelEvaluator::evaluate(
        const float* features, uint8_t n_features) const {
    Result r{};
    r.valid = false;
    if (!ready_ || !schemaOk_) return r;

    FILE* f = fopen(modelPath_, "rb");
    if (!f) return r;

    ModelHeader hdr;
    if (!readBytes(f, &hdr, sizeof(hdr))
        || hdr.magic[0] != 'P' || hdr.magic[1] != 'O'
        || hdr.magic[2] != 'M' || hdr.magic[3] != 'L'
        || hdr.version != MODEL_VERSION) {
        fclose(f); return r;
    }

    uint8_t n_out = (hdr.n_outputs <= MAX_MODEL_OUTPUTS)
                    ? (uint8_t)hdr.n_outputs : MAX_MODEL_OUTPUTS;
    float acc[MAX_MODEL_OUTPUTS] = {};

    // Per-tree buffers (heap alloc to avoid large stack frames)
    size_t split_buf_sz  = (hdr.max_splits + 1) * sizeof(ModelSplitNode);
    size_t leaf_buf_sz   = (hdr.max_splits + 2) * n_out * sizeof(float);
    auto* splits    = (ModelSplitNode*)malloc(split_buf_sz);
    auto* leaf_vals = (float*)malloc(leaf_buf_sz);
    if (!splits || !leaf_vals) {
        free(splits); free(leaf_vals); fclose(f); return r;
    }

    bool ok = true;
    for (uint32_t t = 0; t < hdr.n_trees && ok; t++) {
        ModelTreeHeader th;
        if (!readBytes(f, &th, sizeof(th))) { ok = false; break; }
        if (!readBytes(f, splits,    th.n_splits * sizeof(ModelSplitNode))) { ok = false; break; }
        if (!readBytes(f, leaf_vals, (size_t)th.n_leaves * n_out * sizeof(float))) { ok = false; break; }
        accumulateTree(splits, th.n_splits, leaf_vals, th.n_leaves,
                       features, n_features, acc, n_out);
    }

    free(splits); free(leaf_vals); fclose(f);
    if (!ok) return r;

    memcpy(r.values, acc, n_out * sizeof(float));
    r.n_outputs = n_out;
    r.valid = true;
    return r;
}

#else  // embedded (Arduino + SD.h)

#include <SD.h>

static bool readBytes(File& f, void* buf, size_t n) {
    return (size_t)f.read((uint8_t*)buf, n) == n;
}

bool ModelEvaluator::begin(const char* manifest_path, const char* model_path) {
    ready_ = false; schemaOk_ = false;
    if (!ModelManifest::loadFromSd(manifest_path, manifest_)) return false;
    schemaOk_ = (manifest_.schema_hash == MODEL_SCHEMA_HASH) || (MODEL_SCHEMA_HASH == 0);
    strncpy(modelPath_, model_path, sizeof(modelPath_) - 1);
    ready_ = true;
    return true;
}

ModelEvaluator::Result ModelEvaluator::evaluate(
        const float* features, uint8_t n_features) const {
    Result r{};
    r.valid = false;
    if (!ready_ || !schemaOk_) return r;

    File f = SD.open(modelPath_, FILE_READ);
    if (!f) return r;

    ModelHeader hdr;
    if (!readBytes(f, &hdr, sizeof(hdr))
        || hdr.magic[0] != 'P' || hdr.magic[1] != 'O'
        || hdr.magic[2] != 'M' || hdr.magic[3] != 'L'
        || hdr.version != MODEL_VERSION) {
        f.close(); return r;
    }

    uint8_t n_out = (hdr.n_outputs <= MAX_MODEL_OUTPUTS)
                    ? (uint8_t)hdr.n_outputs : MAX_MODEL_OUTPUTS;
    float acc[MAX_MODEL_OUTPUTS] = {};

    size_t split_buf_sz  = (hdr.max_splits + 1) * sizeof(ModelSplitNode);
    size_t leaf_buf_sz   = (hdr.max_splits + 2) * n_out * sizeof(float);
    auto* splits    = (ModelSplitNode*)malloc(split_buf_sz);
    auto* leaf_vals = (float*)malloc(leaf_buf_sz);
    if (!splits || !leaf_vals) {
        free(splits); free(leaf_vals); f.close(); return r;
    }

    bool ok = true;
    for (uint32_t t = 0; t < hdr.n_trees && ok; t++) {
        ModelTreeHeader th;
        if (!readBytes(f, &th, sizeof(th))) { ok = false; break; }
        if (!readBytes(f, splits,    th.n_splits * sizeof(ModelSplitNode))) { ok = false; break; }
        if (!readBytes(f, leaf_vals, (size_t)th.n_leaves * n_out * sizeof(float))) { ok = false; break; }
        accumulateTree(splits, th.n_splits, leaf_vals, th.n_leaves,
                       features, n_features, acc, n_out);
    }

    free(splits); free(leaf_vals); f.close();
    if (!ok) return r;

    memcpy(r.values, acc, n_out * sizeof(float));
    r.n_outputs = n_out;
    r.valid = true;
    return r;
}

#endif  // NATIVE_TEST
