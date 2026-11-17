import pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rows():
    return (ROOT / "data" / "seed-commands.tsv").read_text().strip().splitlines()


def test_seed_lists_both_platforms():
    rows = _rows()
    ps = {r.split("\t")[0] for r in rows}
    assert "linux" in ps and "windows11" in ps and len(rows) >= 120


def test_seed_rows_well_formed_and_balanced():
    rows = _rows()
    counts = {}
    for r in rows:
        parts = r.split("\t")
        assert len(parts) == 3, parts[:1]
        assert parts[0] in ("linux", "windows11")
        assert parts[1] and " " not in parts[1]
        assert len(parts[2].split()) >= 5
        counts[parts[0]] = counts.get(parts[0], 0) + 1
    assert counts.get("linux", 0) >= 55 and counts.get("windows11", 0) >= 55
    assert len({r.split("\t")[1] for r in rows if r.startswith("linux")}) == counts["linux"]
    assert len({r.split("\t")[1] for r in rows if r.startswith("windows11")}) == counts["windows11"]


def test_builder_composes_card_text_over_floor():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_seed_kb as b
    card = b.card_text("tar", "linux", "Create or extract archives.",
                       "More information: <https://x>.\nMore information: <https://y>.",
                       "- Create an archive:\n\n`tar -czf a.tar.gz dir`")
    assert len(card) > 40 and "tar" in card and "linux" in card
    sys.path.pop(0)
