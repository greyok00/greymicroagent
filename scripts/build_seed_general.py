import json, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services"))
import rag.kbcore as kb

SRC = "greylocalrag product seed (own-written)"
URL = "-"
DB = "general"


def read_rows():
    out = []
    for line in (ROOT / "data" / "seed-general.tsv").read_text(encoding="utf-8").splitlines():
        if line.strip():
            t, h, n = line.split("\t", 2)
            out.append((t.strip(), h.strip(), n.strip()))
    return out


def card_text(topic, title, note):
    return " ".join([f"{topic}: {title}.", note.strip()])


def main():
    rows = read_rows()
    byp = {}
    for t, _h, _n in rows:
        byp[t] = byp.get(t, 0) + 1
    print(f"curated rows: {len(rows)} ({', '.join(f'{k}={v}' for k, v in sorted(byp.items()))})")
    db = kb.db_dir(DB)
    kb.init_db(db, note="general-ability seed cards: writing craft, reasoning discipline, "
                        "browser baseline. Own-written product text, nothing fetched.")
    date = time.strftime("%F")
    added_ids, cards = [], []
    for topic, title, note in rows:
        text = card_text(topic, title, note)
        if len(text) <= 60:
            print(f"SKIP too short {topic}/{title}: card text under the honest-card floor")
            continue
        recs = kb.records_from(text, {"t": f"{topic}: {title}", "src": SRC, "url": URL,
                                      "date": date})
        added = kb.add_records(db, recs, None, src=SRC)
        added_ids += added
        cards.append((f"{topic}: {title}", len(text), len(added)))
        print(f"OK    {topic}: {title} -> {len(added)} record(s), card chars={len(text)}")
    manifest = {"name": DB, "note": "general-ability seed cards (own-written, no fetched text)",
                "src": SRC, "url": URL, "built": date, "rows": len(rows)}
    (db / "seed-provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nadded {len(added_ids)} records across {len(cards)} cards into {db}")
    print(f"provenance: src={SRC} url={URL} date={date}")
    if not added_ids:
        print("NOTHING ADDED: no card could be ingested")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
