#!/usr/bin/env python3
"""
Export a trained LightGBM model to pod binary format (model.bin + manifest.json).

The binary format is defined in pod/src/model/ModelFormat.h.

Usage:
    python pod-ml/scripts/export_model.py \\
        --model pod-ml/models/latest.pkl \\
        --features pressure_hpa temp_c humidity_pct pressure_rate_1h pressure_rate_3h \\
                   hour_sin hour_cos doy_sin doy_cos \\
        --output-names rain_p10_1h rain_p25_1h rain_p50_1h rain_p75_1h rain_p90_1h \\
        --out pod/sd_card/model/

The --features and --output-names lists must match the model's training config.
After export, copy pod/sd_card/model/ to the SD card and update MODEL_SCHEMA_HASH
in pod/src/model/ModelFormat.h with the value printed by this script.
"""

import argparse
import json
import math
import struct
import pickle
import hashlib
from pathlib import Path
from datetime import datetime, timezone


# ── Format constants (must match ModelFormat.h) ───────────────────────────────

MAGIC       = b'POML'
VERSION     = 1
MAX_SPLITS  = 1023


# ── FNV-1a 64-bit hash ────────────────────────────────────────────────────────

def fnv1a64(data: bytes) -> int:
    h = 14695981039346656037
    prime = 1099511628211
    for b in data:
        h ^= b
        h = (h * prime) & 0xFFFFFFFFFFFFFFFF
    return h


def schema_hash(feature_names: list[str]) -> int:
    joined = ','.join(feature_names).encode('utf-8')
    return fnv1a64(joined)


# ── LightGBM tree extraction ──────────────────────────────────────────────────

def extract_trees(booster, n_outputs: int) -> list[dict]:
    """
    Extract all trees from a LightGBM Booster as a list of dicts:
      {splits: [(feature, threshold, left, right), ...], leaf_vals: [[f, ...], ...]}

    For multi-output models (num_class > 1 or multi-output regression):
    LightGBM interleaves trees: tree 0 for output 0, tree 1 for output 1, etc.
    We group them by iteration and emit one combined tree per iteration that
    accumulates into a flat output vector.

    For single-output boosters: each tree contributes to output 0 only.
    """
    model_dict = booster.dump_model()
    raw_trees = model_dict['tree_info']
    n_class = model_dict.get('num_class', 1) or 1
    n_iter = len(raw_trees) // n_class

    # Each 'combined' tree covers one boosting round across all outputs.
    # We emit them as separate trees; the evaluator sums all.
    combined = []
    for i, raw in enumerate(raw_trees):
        out_idx = i % n_class  # which output head this tree updates
        splits = []
        leaves = {}
        _parse_node(raw['tree_structure'], splits, leaves)
        n_leaves = len(leaves)
        # leaf_vals is a 2D array: [leaf_idx][n_outputs], other outputs are 0
        leaf_vals = [[0.0] * n_outputs for _ in range(n_leaves)]
        for leaf_idx, val in leaves.items():
            leaf_vals[leaf_idx][out_idx] = float(val)
        combined.append({'splits': splits, 'leaf_vals': leaf_vals})

    return combined


def _parse_node(node: dict, splits: list, leaves: dict):
    """Recursively parse a LightGBM tree node into splits + leaf lists."""
    if 'leaf_index' in node:
        # Leaf node
        leaves[node['leaf_index']] = node.get('leaf_value', 0.0)
        return node['leaf_index']  # return leaf index (positive integer)

    # Split node
    split_idx = len(splits)
    splits.append(None)  # placeholder

    feature = node['split_feature']
    threshold = float(node['threshold'])

    left_node = node.get('left_child', {})
    right_node = node.get('right_child', {})

    left_result  = _parse_node(left_node,  splits, leaves)
    right_result = _parse_node(right_node, splits, leaves)

    # Encode: split index → positive; leaf index → -(leaf_idx + 1)
    left_enc  = left_result  if isinstance(left_result,  int) and 'left_child'  in left_node  else -(left_result  + 1)
    right_enc = right_result if isinstance(right_result, int) and 'right_child' in right_node else -(right_result + 1)

    # Re-check: if the node had a 'leaf_index' key, it was a leaf
    def encode_child(child_node, result):
        if 'leaf_index' in child_node:
            return -(result + 1)  # leaf
        return result  # split

    splits[split_idx] = (feature, threshold,
                         encode_child(left_node,  left_result),
                         encode_child(right_node, right_result))
    return split_idx


# ── Binary writer ─────────────────────────────────────────────────────────────

def write_model_bin(path: Path, trees: list[dict], n_features: int,
                    n_outputs: int, hash_val: int):
    max_splits = max(len(t['splits']) for t in trees)

    with open(path, 'wb') as f:
        # Global header (28 bytes)
        f.write(MAGIC)
        f.write(struct.pack('<H', VERSION))
        f.write(struct.pack('<H', n_outputs))
        f.write(struct.pack('<I', len(trees)))
        f.write(struct.pack('<I', n_features))
        f.write(struct.pack('<Q', hash_val))
        f.write(struct.pack('<I', max_splits))

        for tree in trees:
            splits    = tree['splits']
            leaf_vals = tree['leaf_vals']
            n_splits  = len(splits)
            n_leaves  = len(leaf_vals)

            f.write(struct.pack('<H', n_splits))
            f.write(struct.pack('<H', n_leaves))

            # Split nodes: feature(u16), threshold(f32), left(i16), right(i16)
            for feature, threshold, left, right in splits:
                f.write(struct.pack('<H', feature))
                f.write(struct.pack('<f', threshold))
                f.write(struct.pack('<h', left))
                f.write(struct.pack('<h', right))

            # Leaf values: n_leaves × n_outputs floats (row-major)
            for lv in leaf_vals:
                for v in lv:
                    f.write(struct.pack('<f', v))


# ── Manifest writer ───────────────────────────────────────────────────────────

def write_manifest(path: Path, feature_names: list[str], output_names: list[str],
                   hash_val: int, model_file: str = 'model.bin'):
    manifest = {
        'version': VERSION,
        'trained_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'model_file': model_file,
        'n_features': len(feature_names),
        'features': feature_names,
        'schema_hash': f'{hash_val:016x}',
        'n_outputs': len(output_names),
        'output_names': output_names,
    }
    with open(path, 'w') as f:
        json.dump(manifest, f, indent=2)


# ── Verify round-trip (sanity check) ─────────────────────────────────────────

def verify_round_trip(model_path: Path, n_features: int, n_outputs: int,
                      n_trees: int, hash_val: int):
    """Basic structural check on the written file."""
    with open(model_path, 'rb') as f:
        magic = f.read(4)
        assert magic == MAGIC, f"Bad magic: {magic}"
        ver, n_out, n_t, n_f = struct.unpack('<HHII', f.read(12))
        assert ver == VERSION
        assert n_out == n_outputs
        assert n_t == n_trees
        assert n_f == n_features
        h, max_s = struct.unpack('<QI', f.read(12))
        assert h == hash_val, f"Hash mismatch: {h:#x} vs {hash_val:#x}"
    print(f"  verify ok: {n_trees} trees, {n_features} features, {n_outputs} outputs")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Export LightGBM model to pod binary format')
    parser.add_argument('--model', required=True, help='Path to trained model (.pkl)')
    parser.add_argument('--features', nargs='+', required=True,
                        help='Feature names in order (must match model training)')
    parser.add_argument('--output-names', nargs='+', required=True,
                        help='Output names (e.g. rain_p50_1h)')
    parser.add_argument('--out', required=True, help='Output directory')
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f'Loading model: {args.model}')
    with open(args.model, 'rb') as f:
        obj = pickle.load(f)

    # Support: raw Booster, sklearn wrapper, or dict with 'booster' key
    import lightgbm as lgb
    if isinstance(obj, lgb.Booster):
        booster = obj
    elif hasattr(obj, 'booster_'):
        booster = obj.booster_
    elif isinstance(obj, dict) and 'booster' in obj:
        booster = obj['booster']
    else:
        raise ValueError(f'Unrecognised model type: {type(obj)}')

    n_features    = len(args.features)
    n_outputs     = len(args.output_names)
    hash_val      = schema_hash(args.features)
    model_file    = 'model.bin'
    manifest_file = 'manifest.json'

    print(f'Schema hash: {hash_val:#018x}')
    print(f'Features ({n_features}): {args.features}')
    print(f'Outputs  ({n_outputs}): {args.output_names}')

    print('Extracting trees...')
    trees = extract_trees(booster, n_outputs)
    print(f'  {len(trees)} trees, max_splits={max(len(t["splits"]) for t in trees)}')

    model_path    = out_dir / model_file
    manifest_path = out_dir / manifest_file

    print(f'Writing {model_path}...')
    write_model_bin(model_path, trees, n_features, n_outputs, hash_val)
    verify_round_trip(model_path, n_features, n_outputs, len(trees), hash_val)

    print(f'Writing {manifest_path}...')
    write_manifest(manifest_path, args.features, args.output_names, hash_val, model_file)

    print()
    print('Done. Now update MODEL_SCHEMA_HASH in pod/src/model/ModelFormat.h:')
    print(f'  static constexpr uint64_t MODEL_SCHEMA_HASH = {hash_val:#018x}ULL;')
    print()
    print('Copy the output directory to the SD card /model/ folder.')


if __name__ == '__main__':
    main()
