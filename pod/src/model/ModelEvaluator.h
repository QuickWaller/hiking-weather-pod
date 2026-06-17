#pragma once
#include <stdint.h>
#include "ModelFormat.h"
#include "ModelManifest.h"

// Streaming LightGBM tree evaluator.
//
// Reads model.bin from SD one tree at a time (peak RAM ≈ one tree).
// Schema-hash gate: if manifest.json schema_hash != MODEL_SCHEMA_HASH,
// evaluate() returns Result{valid=false} and the caller falls back to
// the rule-based algorithm.
//
// Usage:
//   ModelEvaluator eval;
//   if (eval.begin("/model/manifest.json", "/model/model.bin")) {
//       float features[MODEL_N_FEATURES] = { ... };
//       auto r = eval.evaluate(features, MODEL_N_FEATURES);
//       if (r.valid) { /* use r.values[i] */ }
//   }

class ModelEvaluator {
public:
    struct Result {
        float   values[MAX_MODEL_OUTPUTS];
        uint8_t n_outputs;
        bool    valid;
    };

    // Load and validate manifest. Returns false if the manifest is missing,
    // malformed, or its schema_hash doesn't match MODEL_SCHEMA_HASH.
    bool begin(const char* manifest_path, const char* model_path);

    // Run the full forest. Opens model_path, streams trees one at a time.
    // Returns valid=false if the model file can't be opened or schema invalid.
    Result evaluate(const float* features, uint8_t n_features) const;

    bool schemaValid()   const { return schemaOk_; }
    bool isReady()       const { return ready_; }
    const ModelManifest& manifest() const { return manifest_; }

    // Accumulate a single in-memory tree into running sum (exposed for testing).
    static void accumulateTree(
        const ModelSplitNode* splits, uint16_t n_splits,
        const float*          leaf_vals, uint16_t n_leaves,
        const float*          features,  uint8_t  n_features,
        float*                acc,       uint8_t  n_outputs);

private:
    ModelManifest manifest_{};
    char          modelPath_[64]{};
    bool          schemaOk_ = false;
    bool          ready_    = false;
};
