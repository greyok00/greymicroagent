import re, sys, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services"))
import rag.kbcore as kb

SRC = "tldr-pages (CC-BY-4.0)"
PAGE_BASE = "https://raw.githubusercontent.com/tldr-pages/tldr/main/pages"
LICENSE_URL = "https://raw.githubusercontent.com/tldr-pages/tldr/main/LICENSE.md"
LADDER = {"linux": ("linux", "common"), "windows11": ("windows", "common")}
SPACING = 3.0
DB = "commands"


def read_rows():
    out = []
    for line in (ROOT / "data" / "seed-commands.tsv").read_text(encoding="utf-8").splitlines():
        if line.strip():
            p, c, n = line.split("\t", 2)
            out.append((p.strip(), c.strip(), n.strip()))
    return out


def _one_line(text):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    return lines[0] if lines else ""


def card_text(command, platform, synopsis, more_info, example, note=""):
    m = re.search(r"`([^`]+)`", example or "")
    ex = m.group(1) if m else re.sub(r"\s+", " ", example or "")
    ex = ex.replace("{", "").replace("}", "").strip()
    syn = _one_line(re.sub(r"[\n>]+", " ", synopsis or "")).rstrip(".")
    mi = _one_line(more_info or "")
    mi = re.sub(r"^more information:\s*", "", mi, flags=re.I).strip()
    mu = re.search(r"<(\S+?)>", mi)
    mi = mu.group(1) if mu else mi.strip(".")
    parts = [f"{platform} command {command}."]
    if note:
        parts.append(note.strip())
    if syn:
        parts.append(f"Synopsis: {syn}.")
    if ex:
        parts.append(f"Typical usage: {ex}.")
    if mi:
        parts.append(f"Reference page: {mi}.")
    return " ".join(parts)


def parse_page(raw):
    mt = re.search(r"(?:^|\n)#\s+([^\n]+)", raw)
    title = mt.group(1).strip() if mt else ""
    mb = re.search(r"(?:^|\n)>(?:[^\n]*)(?:\n>[^\n]*)*", raw)
    syn, mi = [], ""
    for line in (mb.group(0) if mb else "").splitlines():
        s = line.lstrip("> ").strip()
        if not s:
            continue
        if s.lower().startswith("more information:"):
            mi = s
        else:
            syn.append(s)
    pair = re.search(r"(?:^|\n)- ([^\n]+):\s*\n\s*`([^`]+)`", raw)
    example = f"- {re.sub(r'`', '', pair.group(1)).strip()}:\n\n`{pair.group(2).strip()}`" if pair else (
        "`" + re.search(r"`([^`]+)`", raw).group(1).strip() + "`"
        if re.search(r"`([^`]+)`", raw) else "")
    if not syn:
        syn.append(title)
    return title, "\n".join(syn), mi, example


def fetch_page(platform, command):
    for d in LADDER[platform]:
        url = f"{PAGE_BASE}/{d}/{command}.md"
        ok, data, _ct, status = kb.fetch(url)
        if ok:
            return url, data.decode("utf-8", "ignore")
        if status == 404:
            time.sleep(SPACING)
            continue
        raise RuntimeError(f"network lane down at {url}: status {status}: {data[:200]!r}")
    return None, None


def main():
    rows = read_rows()
    byp = {}
    for p, _c, _n in rows:
        byp[p] = byp.get(p, 0) + 1
    print(f"curated rows: {len(rows)} ({', '.join(f'{k}={v}' for k, v in sorted(byp.items()))})")
    db = kb.db_dir(DB)
    kb.init_db(db, note="seed command reference built from tldr-pages (CC-BY-4.0)")
    date = time.strftime("%F")
    fetched, skipped, added_ids = [], [], []
    for platform, command, note in rows:
        try:
            url, raw = fetch_page(platform, command)
        except RuntimeError as e:
            print(f"BLOCKED: {e}")
            return 2
        if url is None:
            line = f"SKIP 404 {platform}/{command}: no page at pages/{LADDER[platform][0]} or pages/common/{command}.md - not ingested, nothing invented"
            print(line)
            skipped.append(line)
            continue
        title, syn, mi, example = parse_page(raw)
        text = card_text(command, platform, syn, mi, example, note)
        recs = kb.records_from(text, {"t": f"{platform} command {command}",
                                      "src": SRC, "url": url, "date": date})
        added = kb.add_records(db, recs, None, src=SRC)
        added_ids += added
        fetched.append(url)
        print(f"OK    {url} -> {len(added)} record(s), card chars={len(text)}")
        time.sleep(SPACING)
    lines = ["Third-party notices for the greylocalrag seed commands knowledge base.",
             "",
             "The records in the 'commands' knowledge base were built from the tldr-pages",
             "project at build time: https://github.com/tldr-pages/tldr",
             "Those pages are licensed under the Creative Commons Attribution 4.0",
             "International License (CC-BY-4.0): https://creativecommons.org/licenses/by/4.0/",
             "License file as fetched at build time: " + LICENSE_URL,
             "This product stores condensed cards (command name, an original-authored usage",
             "note, the page synopsis, one usage example and a link), not verbatim pages,",
             "with per-record attribution (source, url, build date) retained in the database.",
             f"Build date: {date}",
             f"Pages fetched and ingested: {len(fetched)} of {len(rows)} curated rows",
             f"Pages skipped because no page exists at the pinned path: {len(skipped)}",
             ""]
    lines += ["Fetched pages:"]
    lines += [f"  {u}" for u in fetched]
    if skipped:
        lines += ["", "Skipped pages (404, nothing invented in their place):"]
        lines += [f"  {s}" for s in skipped]
    (ROOT / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nadded {len(added_ids)} records into {db}")
    print(f"fetched {len(fetched)}, skipped {len(skipped)}; notices written to {ROOT / 'THIRD-PARTY-NOTICES.txt'}")
    if not added_ids:
        print("NOTHING ADDED: no page could be ingested")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
