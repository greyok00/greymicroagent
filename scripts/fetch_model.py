import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/grey/llama.cpp/gguf-py")

import numpy as np
import gguf

MODEL_REF = "huihui_ai/qwen3-vl-abliterated:2b"
HF_BASE_REPO = "Qwen/Qwen3-VL-2B-Instruct"
SOURCE_BLOB = "/usr/share/ollama/.ollama/models/blobs/sha256-20ef83c3cae84e1dc03d3faee31c3c4ddda6ca806a8c99dc89d42e3e43e9c2ff"
SOURCE_BLOB_SHA256 = "20ef83c3cae84e1dc03d3faee31c3c4ddda6ca806a8c99dc89d42e3e43e9c2ff"
TARGET = Path.home() / ".greylocalrag" / "models" / "qwen3-vl-2b-abliterated.gguf"
REPAIR_KEY = "qwen3vl.rope.dimension_sections"
REPAIR_VALUE = [24, 20, 20, 0]
EXPECTED_PATCHED_SHA256 = "9a6993557cf0137733a7e520e05757b2f7f3df437bbe50f71d1a0afb64acfd9b"

PSEUDO = ("GGUF.",)


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


def tensor_fingerprints(reader):
    out = {}
    for t in reader.tensors:
        h = hashlib.sha256()
        flat = t.data.reshape(-1)
        for off in range(0, flat.nbytes, 1 << 24):
            h.update(flat[off:off + (1 << 24)].tobytes())
        out[t.name] = (hashlib.sha256(str(tuple(t.shape)).encode()).hexdigest(),
                       int(t.tensor_type), int(t.n_elements), h.hexdigest())
    return out


def check(source_reader, patched_path):
    patched = gguf.GGUFReader(str(patched_path), "r")
    with open(patched_path, "rb") as f:
        assert f.read(4) == b"GGUF", "patched file lost GGUF magic"
    pk = kv_map(patched)
    sk = kv_map(source_reader)
    assert len(patched.tensors) == len(source_reader.tensors), "tensor count changed"
    assert REPAIR_KEY not in sk, "source already carries the repair key"
    assert pk[REPAIR_KEY] == REPAIR_VALUE, "repair key wrong value %r" % pk[REPAIR_KEY]
    del pk[REPAIR_KEY]
    missing = set(sk) - set(pk)
    assert not missing, "lost kv keys %r" % sorted(missing)[:10]
    diffs = [k for k in sk if k in pk and pk[k] != sk[k]]
    assert not diffs, "kv value drift %r" % diffs[:10]
    sf, pf = tensor_fingerprints(source_reader), tensor_fingerprints(patched)
    drifted = [n for n in sf if sf[n] != pf.get(n)]
    assert not drifted, "tensor bytes drifted %r" % drifted[:10]
    log("verified keys=%d tensors=%d weights byte-identical" % (len(pk) + 1, len(pf)))


def build(out_path):
    src_sha = file_sha(SOURCE_BLOB)
    assert src_sha == SOURCE_BLOB_SHA256, "source blob sha mismatch %s" % src_sha
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
    total = 0
    for t in reader.tensors:
        total += t.n_bytes
        writer.add_tensor_info(t.name, t.data.shape, t.data.dtype, t.data.nbytes, t.tensor_type)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_ti_data_to_file()
    for t in reader.tensors:
        writer.write_tensor_data(t.data, tensor_endianess=reader.endianess)
    writer.close()
    check(reader, out_path)
    return arch


def patch():
    tmp = TARGET.with_name(TARGET.name + ".patching")
    log("patching %s -> %s" % (SOURCE_BLOB, tmp))
    build(tmp)
    os.replace(tmp, TARGET)
    log("replaced symlink with patched file: %s" % TARGET)
    log("file_sha256=%s" % file_sha(TARGET))


def verify():
    assert TARGET.is_file() and not TARGET.is_symlink(), "target not a real patched file: %s" % TARGET
    assert EXPECTED_PATCHED_SHA256, "pinned sha not recorded yet"
    sha = file_sha(TARGET)
    assert sha == EXPECTED_PATCHED_SHA256, "sha drift %s != %s" % (sha, EXPECTED_PATCHED_SHA256)
    assert file_sha(SOURCE_BLOB) == SOURCE_BLOB_SHA256, "source blob drifted"
    reader = gguf.GGUFReader(SOURCE_BLOB, "r")
    check(reader, TARGET)
    log("pinned model verified: %s" % TARGET)


def main(argv):
    verb = argv[1] if len(argv) > 1 else "ensure"
    if verb == "patch":
        patch()
    elif verb == "verify":
        verify()
    elif verb == "ensure":
        if TARGET.is_symlink() or not TARGET.exists():
            patch()
        else:
            verify()
    else:
        raise SystemExit("unknown verb %r (patch|verify|ensure)" % verb)


if __name__ == "__main__":
    main(sys.argv)
