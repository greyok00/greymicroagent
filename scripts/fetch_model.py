import hashlib
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "/home/grey/llama.cpp/gguf-py")

import numpy as np
import gguf

MODEL_REF = "huihui_ai/qwen3-vl-abliterated:2b"
HF_BASE_REPO = "Qwen/Qwen3-VL-2B-Instruct"
SOURCE_BLOB = "/usr/share/ollama/.ollama/models/blobs/sha256-20ef83c3cae84e1dc03d3faee31c3c4ddda6ca806a8c99dc89d42e3e43e9c2ff"
SOURCE_BLOB_SHA256 = "20ef83c3cae84e1dc03d3faee31c3c4ddda6ca806a8c99dc89d42e3e43e9c2ff"
MODELS_DIR = Path.home() / ".greylocalrag" / "models"
FUSED = MODELS_DIR / "qwen3-vl-2b-abliterated-fused.gguf"
TEXT = MODELS_DIR / "qwen3-vl-2b-abliterated.gguf"
MMPROJ = MODELS_DIR / "qwen3-vl-2b-mmproj.gguf"
REPAIR_KEY = "qwen3vl.rope.dimension_sections"
REPAIR_VALUE = [24, 20, 20, 0]
DEEPSTACK_KEY = "qwen3vl.num_deepstack_layers"
VISION_PREFIX = "qwen3vl.vision."
FILE_TYPE_F16 = 1
EXPECTED_FUSED_SHA256 = "9a6993557cf0137733a7e520e05757b2f7f3df437bbe50f71d1a0afb64acfd9b"
EXPECTED_TEXT_SHA256 = "37f662a20158437fee35b1aa5a472748c9915f561b928fca01812d3139848a1f"
EXPECTED_MMPROJ_SHA256 = "5ecc02db0f85888bdae69b567034530befcfe11ac84e0a0297ec187f0f05786c"

PSEUDO = ("GGUF.",)
_SRC = None
MKV_EXPECT = {
    "clip.projector_type": "qwen3vl_merger",
    "clip.has_vision_encoder": True,
    "clip.use_gelu": True,
    "clip.vision.projection_dim": 2048,
    "clip.vision.embedding_length": 1024,
    "clip.vision.feed_forward_length": 4096,
    "clip.vision.block_count": 24,
    "clip.vision.attention.head_count": 16,
    "clip.vision.image_size": 768,
    "clip.vision.patch_size": 16,
    "clip.vision.spatial_merge_size": 2,
}


def log(msg):
    print(msg, flush=True)


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_field(field):
    c = field.contents()
    if isinstance(c, np.ndarray):
        return [tuple(x) for x in c.tolist()] if c.ndim > 1 else c.tolist()
    if isinstance(c, list):
        return [tuple(x) if isinstance(x, np.ndarray) else x for x in c]
    if isinstance(c, np.generic):
        return c.item()
    return c


def kv_map(reader):
    return {f.name: norm_field(f) for f in reader.fields.values()
            if not f.name.startswith(PSEUDO) and f.name != gguf.Keys.General.ARCHITECTURE}


def sha_tensor(t):
    h = hashlib.sha256()
    flat = t.data.reshape(-1)
    for off in range(0, flat.nbytes, 1 << 24):
        h.update(flat[off:off + (1 << 24)].tobytes())
    return h.hexdigest()


def tensor_fingerprints(reader):
    return {t.name: (tuple(int(x) for x in t.shape), int(t.tensor_type), sha_tensor(t))
            for t in reader.tensors}


def build_fused(out_path):
    assert file_sha(SOURCE_BLOB) == SOURCE_BLOB_SHA256, "source blob drifted"
    reader = gguf.GGUFReader(SOURCE_BLOB, "r")
    arch = reader.get_field(gguf.Keys.General.ARCHITECTURE).contents()
    writer = gguf.GGUFWriter(str(out_path), arch=arch, endianess=reader.endianess)
    alignment = reader.get_field(gguf.Keys.General.ALIGNMENT)
    if alignment is not None:
        writer.data_alignment = int(alignment.contents())
    for field in reader.fields.values():
        if field.name.startswith(PSEUDO) or field.name == gguf.Keys.General.ARCHITECTURE:
            continue
        writer.add_key_value(field.name, field.contents(), field.types[0],
                             sub_type=field.types[-1] if field.types[0] == gguf.GGUFValueType.ARRAY else None)
    writer.add_key_value(REPAIR_KEY, REPAIR_VALUE, gguf.GGUFValueType.ARRAY, sub_type=gguf.GGUFValueType.INT32)
    for t in reader.tensors:
        writer.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    for t in reader.tensors:
        writer.write_tensor_data(t.data, tensor_endianess=reader.endianess)
    writer.close()
    out_reader = gguf.GGUFReader(str(out_path), "r")
    out_kv = kv_map(out_reader)
    src_kv = kv_map(reader)
    assert out_kv[REPAIR_KEY] == REPAIR_VALUE, "repair key bad"
    del out_kv[REPAIR_KEY]
    assert set(src_kv) == set(out_kv), "kv keys lost"
    for k in src_kv:
        assert out_kv[k] == src_kv[k], "kv drift on %s" % k
    assert len(out_reader.tensors) == len(reader.tensors) == 721
    assert tensor_fingerprints(reader) == tensor_fingerprints(out_reader), "tensor bytes drifted"


def _deepstack_map(kv):
    idx = kv.get(VISION_PREFIX + "deepstack_visual_indexes")
    assert idx == [5, 11, 17], "deepstack indexes unexpected %r" % (idx,)
    return {0: 5, 1: 11, 2: 17}


def _v_rename(name, deep):
    renames = {
        "v.patch_embed.bias": "v.patch_embd.bias",
        "v.pos_embed.weight": "v.position_embd.weight",
        "v.merger.norm.weight": "v.post_ln.weight",
        "v.merger.norm.bias": "v.post_ln.bias",
        "v.merger.linear_fc1.weight": "mm.0.weight",
        "v.merger.linear_fc1.bias": "mm.0.bias",
        "v.merger.linear_fc2.weight": "mm.2.weight",
        "v.merger.linear_fc2.bias": "mm.2.bias",
    }
    if name in renames:
        return renames[name]
    if name == "v.patch_embed.weight":
        return "v.patch_embd.weight"
    m = re.fullmatch(r"v\.deepstack_merger\.(\d+)\.(norm|linear_fc1|linear_fc2)\.(weight|bias)", name)
    if m:
        kind = {"norm": "norm", "linear_fc1": "fc1", "linear_fc2": "fc2"}[m.group(2)]
        return "v.deepstack.%d.%s.%s" % (deep[int(m.group(1))], kind, m.group(3))
    if name.startswith("v.blk."):
        tail = re.sub(r"^(\d+)\.norm1\.", r"\1.ln1.", name[len("v.blk."):])
        tail = re.sub(r"^(\d+)\.norm2\.", r"\1.ln2.", tail)
        tail = re.sub(r"^(\d+)\.mlp\.linear_fc1\.", r"\1.ffn_up.", tail)
        tail = re.sub(r"^(\d+)\.mlp\.linear_fc2\.", r"\1.ffn_down.", tail)
        return "v.blk." + tail
    raise KeyError("unplanned vision tensor %r" % name)


def _plan(reader, kv):
    deep = _deepstack_map(kv)
    plan = []
    for t in reader.tensors:
        name = t.name
        if not name.startswith("v."):
            continue
        plan.append((_v_rename(name, deep), t, "COPY", 0))
    return plan


def _write(path, arch, kvs, tensors):
    writer = gguf.GGUFWriter(str(path), arch=arch)
    for key, val, vtype, sub in kvs:
        writer.add_key_value(key, val, vtype, sub_type=sub)
    for name, arr, raw in tensors:
        writer.add_tensor(name, arr, raw_dtype=raw)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    for _, arr, raw in tensors:
        writer.write_tensor_data(arr, tensor_endianess=gguf.GGUFEndian.LITTLE)
    writer.close()


def _mm_kvs(kv):
    by_name = {t.name: t for t in _SRC.tensors}
    n_embd_text = int(kv["qwen3vl.embedding_length"])
    fc1 = by_name["v.blk.0.mlp.linear_fc1.weight"]
    pos_w = by_name["v.pos_embed.weight"]
    patch_size = int(kv[VISION_PREFIX + "patch_size"])
    image_size = int(math.isqrt(int(pos_w.shape[1])) * patch_size)
    return [
        ("general.quantization_version", 2, gguf.GGUFValueType.UINT32, None),
        ("general.file_type", FILE_TYPE_F16, gguf.GGUFValueType.UINT32, None),
        ("clip.has_vision_encoder", True, gguf.GGUFValueType.BOOL, None),
        ("clip.projector_type", "qwen3vl_merger", gguf.GGUFValueType.STRING, None),
        ("clip.use_gelu", True, gguf.GGUFValueType.BOOL, None),
        ("clip.vision.projection_dim", n_embd_text, gguf.GGUFValueType.UINT32, None),
        ("clip.vision.embedding_length", int(kv[VISION_PREFIX + "embedding_length"]), gguf.GGUFValueType.UINT32, None),
        ("clip.vision.feed_forward_length", int(fc1.shape[1]), gguf.GGUFValueType.UINT32, None),
        ("clip.vision.block_count", int(kv[VISION_PREFIX + "block_count"]), gguf.GGUFValueType.UINT32, None),
        ("clip.vision.attention.head_count", int(kv[VISION_PREFIX + "attention.head_count"]), gguf.GGUFValueType.UINT32, None),
        ("clip.vision.attention.layer_norm_epsilon", float(kv[VISION_PREFIX + "attention.layer_norm_epsilon"]), gguf.GGUFValueType.FLOAT32, None),
        ("clip.vision.image_size", image_size, gguf.GGUFValueType.UINT32, None),
        ("clip.vision.patch_size", patch_size, gguf.GGUFValueType.UINT32, None),
        ("clip.vision.spatial_merge_size", int(kv[VISION_PREFIX + "spatial_merge_size"]), gguf.GGUFValueType.UINT32, None),
        ("clip.vision.image_mean", [np.float32(x) for x in kv[VISION_PREFIX + "image_mean"]], gguf.GGUFValueType.ARRAY, gguf.GGUFValueType.FLOAT32),
        ("clip.vision.image_std", [np.float32(x) for x in kv[VISION_PREFIX + "image_std"]], gguf.GGUFValueType.ARRAY, gguf.GGUFValueType.FLOAT32),
    ]


def _mm_tensors(plan):
    return [(out_name, t.data, t.tensor_type if t.data.dtype == np.uint8 else None)
            for out_name, t, kind, _ in plan]


def split():
    global _SRC
    assert file_sha(FUSED) == EXPECTED_FUSED_SHA256, "fused link drifted"
    reader = gguf.GGUFReader(str(FUSED), "r")
    _SRC = reader
    kv = kv_map(reader)
    deep = _deepstack_map(kv)

    text_kvs = []
    for field in reader.fields.values():
        if field.name.startswith(PSEUDO) or field.name == gguf.Keys.General.ARCHITECTURE:
            continue
        if field.name.startswith(VISION_PREFIX):
            continue
        text_kvs.append((field.name, field.contents(), field.types[0],
                         field.types[-1] if field.types[0] == gguf.GGUFValueType.ARRAY else None))
    text_kvs.append((DEEPSTACK_KEY, len(deep), gguf.GGUFValueType.UINT32, None))
    text_tensors = [(t.name, t.data, t.tensor_type if t.data.dtype == np.uint8 else None)
                    for t in reader.tensors if not t.name.startswith("v.")]
    assert len(text_tensors) == 310, "text tensor count %d" % len(text_tensors)

    tmp_text = TEXT.with_name(TEXT.name + ".splitting")
    _write(tmp_text, "qwen3vl", text_kvs, text_tensors)
    _verify_text(reader, tmp_text)
    os.replace(tmp_text, TEXT)
    log("text_sha256=%s" % file_sha(TEXT))
    MMPROJ.unlink(missing_ok=True)

    plan = _plan(reader, kv)
    mm_tensors = _mm_tensors(plan)
    assert len(mm_tensors) == 411, "mmproj tensor count %d" % len(mm_tensors)
    tmp_mm = MMPROJ.with_name(MMPROJ.name + ".splitting")
    _write(tmp_mm, "clip", _mm_kvs(kv), mm_tensors)
    _verify_mm(reader, tmp_mm)
    os.replace(tmp_mm, MMPROJ)
    log("mmproj_sha256=%s" % file_sha(MMPROJ))


def _verify_text(src, text_path):
    tr = gguf.GGUFReader(str(text_path), "r")
    tf = tensor_fingerprints(tr)
    tkv = kv_map(tr)
    src_kv = kv_map(src)
    assert tkv[REPAIR_KEY] == REPAIR_VALUE and tkv[DEEPSTACK_KEY] == 3
    assert not any(k.startswith(VISION_PREFIX) for k in tkv)
    for k, v in src_kv.items():
        if k.startswith(VISION_PREFIX):
            continue
        assert tkv.get(k) == v, "text kv drift on %s" % k
    assert len(tr.tensors) == 310
    sf = tensor_fingerprints(src)
    assert tf == {n: f for n, f in sf.items() if not n.startswith("v.")}, "text tensor drift"


def _verify_mm(src, mm_path):
    mr = gguf.GGUFReader(str(mm_path), "r")
    mf = tensor_fingerprints(mr)
    mkv = kv_map(mr)
    for k, v in MKV_EXPECT.items():
        assert mkv[k] == v, "mmproj kv %s=%r != %r" % (k, mkv[k], v)
    assert mkv["clip.vision.image_mean"] == [0.5, 0.5, 0.5]
    assert mkv["clip.vision.image_std"] == [0.5, 0.5, 0.5]
    assert len(mr.tensors) == 411
    sf = tensor_fingerprints(src)
    plan = _plan(src, kv_map(src))
    assert set(mf) == {p[0] for p in plan}, "output tensor set mismatch"
    for out_name, t, kind, _ in plan:
        assert mf[out_name] == sf[t.name], "mmproj tensor drift %r" % out_name
    log("mmproj verified: 411 tensors sha-identical")


def chain():
    tmp = FUSED.with_name(FUSED.name + ".patching")
    build_fused(tmp)
    built = file_sha(tmp)
    assert built == EXPECTED_FUSED_SHA256, "fused sha drifted %s" % built
    os.replace(tmp, FUSED)
    log("fused_sha256=%s" % built)
    split()


def verify():
    reader = gguf.GGUFReader(str(FUSED), "r")
    _verify_text(reader, TEXT)
    got = file_sha(TEXT)
    assert EXPECTED_TEXT_SHA256 and got == EXPECTED_TEXT_SHA256, "text sha %s not pinned" % got
    assert not TEXT.is_symlink() and TEXT.is_file()
    assert MMPROJ.is_file()
    _verify_mm(reader, MMPROJ)
    got = file_sha(MMPROJ)
    assert EXPECTED_MMPROJ_SHA256 and got == EXPECTED_MMPROJ_SHA256, "mmproj sha %s not pinned" % got
    log("pinned chain verified")


def main(argv):
    verb = argv[1] if len(argv) > 1 else "ensure"
    if verb == "chain":
        chain()
    elif verb == "split":
        split()
    elif verb == "verify":
        verify()
    elif verb == "ensure":
        chain()
    else:
        raise SystemExit("unknown verb %r (chain|split|verify|ensure)" % verb)


if __name__ == "__main__":
    main(sys.argv)
