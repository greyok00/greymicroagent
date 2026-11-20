from __future__ import annotations

from core import registry
from core.registry import _schema

_state = {"done": False}


def _cap_json(obj, limit: int = 100000) -> str:
    """Serialize a tool result without ever cutting JSON mid-string.

    A raw [:40000] slice produced "Unterminated string in JSON" whenever a RAG
    record carried a long page; shorten strings/lists first, and fall back to a
    valid summary if it still does not fit.
    """
    import json as _cj

    def shrink(value):
        if isinstance(value, str):
            return value if len(value) <= 2000 else value[:2000] + "..."
        if isinstance(value, list):
            return [shrink(item) for item in value[:2000]]
        if isinstance(value, dict):
            return {key: shrink(item) for key, item in value.items()}
        return value

    try:
        text = _cj.dumps(shrink(obj), default=str)
    except Exception:
        return _cj.dumps({"error": "unserializable result"})
    if len(text) <= limit:
        return text
    return _cj.dumps({"truncated": True,
                      "note": "result too large; strings and lists were shortened"})


def register_all() -> int:
    if _state["done"]:
        return len(registry.list_tools())
    from core.subagent import spawn as _spawn
    registry.register_tool("spawn_subagent", _schema(
        "Run a sub-task with the local model.",
        {"prompt": {"type": "string"}}, ["prompt"]), _spawn)

    from tools import files as files_mod
    registry.register_tool("files_read", _schema(
        "Read file. args: path", {"path": {"type": "string"}}, ["path"]),
        files_mod.read_file)
    registry.register_tool("files_write", _schema(
        "Write file. args: path, content",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"]), files_mod.write_file)
    registry.register_tool("files_edit", _schema(
        "Edit file. args: path, old, new",
        {"path": {"type": "string"}, "old": {"type": "string"},
         "new": {"type": "string"}}, ["path", "old", "new"]),
        files_mod.edit_file)
    registry.register_tool("files_list", _schema(
        "List dir. args: path", {"path": {"type": "string"}}, ["path"]),
        files_mod.list_dir)
    registry.register_tool("files_delete", _schema(
        "Delete path.",
        {"path": {"type": "string"}}, ["path"]), files_mod.delete_file)

    from tools import search as search_mod
    registry.register_tool("search_files", _schema(
        "Glob files. args: pattern",
        {"pattern": {"type": "string"}, "base": {"type": "string"}},
        ["pattern"]), search_mod.glob)
    registry.register_tool("search_grep", _schema(
        "Grep files. args: pattern",
        {"pattern": {"type": "string"}, "base": {"type": "string"},
         "glob_filter": {"type": "string"}}, ["pattern"]), search_mod.grep)

    def shell_kw(**kw) -> dict:
        cmd = kw.get("command") or kw.get("cmd") or kw.get("bash") or kw.get("script")
        if cmd is None and isinstance(kw.get("args"), str):
            cmd = kw["args"]
        if cmd is None:
            return {"ok": False, "output": "", "error": "missing argument: command"}
        return registry._run_command(str(cmd), int(kw.get("timeout") or 3600))

    registry.register_tool("shell", _schema(
        "Bash. args: command",
        {"command": {"type": "string"}}, ["command"]), shell_kw)

    def web_search(query: str = "", max_results: int = 12, **kw) -> dict:
        from tools.research_integration import research_search
        q = query or kw.get("q") or kw.get("search")
        if not q:
            return {"ok": False, "output": "", "error": "missing argument: query"}
        r = research_search(q, max_results=max_results)
        r.setdefault("trust", "high")
        return r

    def web_fetch(url: str = "", max_chars: int = 20000, **kw) -> dict:
        # 2026-11-19: the research stack needs browser-ports.json this fork
        # does not ship, so web_fetch failed on every URL while browser_open
        # worked. Route through the browser service that already works.
        u = url or kw.get("uri") or kw.get("page")
        if not u:
            return {"ok": False, "output": "", "error": "missing argument: url"}
        if not (str(u).startswith("http://") or str(u).startswith("https://")):
            return {"ok": False, "output": "", "error": "web_fetch needs an http(s) url"}
        from services import browser_mcp as _b
        try:
            r = _b.dispatch("browser_open", {"url": str(u)})
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        if isinstance(r, dict):
            err = r.get("error") or ""
            text = r.get("text") or r.get("output") or ""
            if isinstance(text, str) and text:
                text = text[:max_chars]
            return {"ok": not err, "output": text if isinstance(text, str)
                    else _json.dumps(r, default=str)[:max_chars],
                    "error": err, "trust": "high"}
        return {"ok": True, "output": str(r)[:max_chars], "error": "", "trust": "high"}

    registry.register_tool("web_search", _schema(
        "Web search via local lanes and the browser scraper; results are "
        "cleaned and relevance-filtered. Parameter: query (string).",
        {"query": {"type": "string"}}, ["query"]), web_search)
    registry.register_tool("web_fetch", _schema(
        "Fetch one URL in the headless browser; returns cleaned text. "
        "Parameter: url (string).",
        {"url": {"type": "string"}}, ["url"]), web_fetch)

    def browser_open(url: str = "", **kw) -> dict:
        u = str(url or kw.get("page") or kw.get("uri") or "")
        if not u:
            return {"ok": False, "output": "", "error": "missing argument: url"}
        if not (u.startswith("http://") or u.startswith("https://")):
            return {"ok": False, "output": "",
                    "error": "browser_open needs an http(s) url"}
        from services import browser_mcp as _b
        try:
            r = _b.dispatch("browser_open", {"url": u})
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        err = r.get("error") if isinstance(r, dict) else ""
        return {"ok": not err, "output": (r if isinstance(r, str)
                                          else _json.dumps(r, default=str))[:40000],
                "error": err or ""}

    def browser_close(**kw) -> dict:
        from services import browser_mcp as _b
        try:
            r = _b.dispatch("browser_close", {})
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _json.dumps(r, default=str))[:8000],
                "error": ""}

    registry.register_tool("browser_open", _schema(
        "Read ONE web page in a real headless chromium: follow redirects, "
        "return title, text, url_final, links, status. http(s) urls only. "
        "Parameter: url (string).",
        {"url": {"type": "string"}}, ["url"]), browser_open)

    registry.register_tool("browser_close", _schema(
        "Free the shared browser opened by browser_open. Idempotent.",
        {}, []), browser_close)

    from tools import browser_tools as browser_mod
    browser_mod.register_browser_tools()
    # 2026-11-19: the registered schema exposes tag/class_fragment, but the
    # underlying fill_and_send() accepts only tab/text/iframe_marker/submit.
    # Passing tag crashed before any browser work; filter at the boundary.
    _fs = getattr(registry, "TOOLS", {}).get("chrome_fill_send")
    if _fs and callable(_fs.get("handler")):
        _orig_fs = _fs["handler"]

        def _fs_filtered(**kw):
            # The stock wrapper injects its own `tag` default, so filtering the
            # caller's kwargs is not enough. Call the implementation directly
            # with only the parameters it actually accepts.
            from tools import browser_control as _bc
            try:
                out = _bc.fill_and_send(
                    tab=kw.get("tab"),
                    text=str(kw.get("text", "") or ""),
                    iframe_marker=str(kw.get("iframe_marker", "") or ""),
                    submit=bool(kw.get("submit", True)),
                )
                return {"ok": True, "output": str(out), "error": ""}
            except Exception as e:
                return {"ok": False, "output": "",
                        "error": "Fill/send failed: %s" % str(e)[:400]}

        _fs["handler"] = _fs_filtered

    from services import memory_thin
    registry.register_tool("memory_append", _schema(
        "Save memory. args: content",
        {"content": {"type": "string"}}, ["content"]),
        lambda content, role="user", **kw:
        {"ok": True, "output": memory_thin.append(content, role), "error": ""})
    registry.register_tool("memory_search", _schema(
        "Search memory. args: query",
        {"query": {"type": "string"}}, ["query"]),
        lambda query, **kw: {"ok": True, "output": memory_thin.search(query),
                             "error": ""})
    registry.register_tool("memory_read", _schema(
        "Recent memory.", {}, []),
        lambda n=5, **kw: {"ok": True, "output": memory_thin.read_last(n),
                           "error": ""})

    def memory_report(**kw) -> dict:
        # 2026-11-19 (owner: memory must check BOTH internal memory and the
        # RAG). A 2B answers after the first read and never issues the second
        # call, so one tool returns both in a single round-trip. The report is
        # a compact summary: collections, counts, and a sample of sources.
        import os as _os
        out = {"internal_memory": [], "rag_collections": [], "rag_sources": {}}

        def _unpack(res):
            payload = res.get("output") if isinstance(res, dict) else res
            if isinstance(payload, str):
                try:
                    payload = _json.loads(payload)
                except Exception:
                    pass
            return payload if isinstance(payload, dict) else {}

        try:
            out["internal_memory"] = memory_thin.read_last(10)
        except Exception as e:
            out["internal_memory"] = "unavailable: %s" % e
        try:
            st = _unpack(rag_pass("rag_status", {}))
            out["rag_collections"] = st.get("dbs") or []
            out["rag_total_records"] = st.get("records")
            dbs = [d.strip() for d in
                   (_os.environ.get("GREYMICROAGENT_DBS") or "commands,general").split(",")
                   if d.strip()]
            for d in dbs:
                pay = _unpack(rag_pass("rag_list_sources", {"db": d}))
                urls = [s.get("url") for s in (pay.get("sources") or [])
                        if isinstance(s, dict)][:10]
                out["rag_sources"][d] = {"distinct": pay.get("distinct"),
                                         "sample": urls}
        except Exception as e:
            out["rag"] = "unavailable: %s" % e
        return {"ok": True, "output": _json.dumps(out, default=str)[:8000],
                "error": ""}

    registry.register_tool("memory_report", _schema(
        "Report BOTH stores: recent internal memory and the RAG collections and sources.",
        {}, []), memory_report)

    from services.scheduler_store import Store
    _sched = Store()
    registry.register_tool("scheduler_add", _schema(
        "Schedule task. args: title, prompt",
        {"title": {"type": "string"}, "kind": {"type": "string"},
         "prompt": {"type": "string"}}, ["title"]),
        lambda title, kind="user", prompt="", **kw: {"ok": True,
            "output": str(_sched.create(title=title, kind=kind,
                                        payload={"prompt": prompt} if prompt else None)),
            "error": ""})
    registry.register_tool("scheduler_list", _schema(
        "List scheduler tasks.", {}, []),
        lambda **kw: {"ok": True, "output": str(_sched.list()), "error": ""})

    import platform as _platform
    import subprocess as _subprocess

    def terminal(command: str = "", timeout: int = 3600, **kw) -> dict:
        c = command or kw.get("cmd") or kw.get("args") or ""
        if not c:
            return {"ok": False, "output": "", "error": "missing argument: command"}
        t = max(1, min(int(timeout or 3600), 86400))
        if _platform.system() == "Windows":
            argv = ["powershell", "-NoProfile", "-Command", str(c)]
        else:
            argv = ["/bin/bash", "-c", str(c)]
        try:
            p = _subprocess.run(argv, capture_output=True, text=True, timeout=t)
        except _subprocess.TimeoutExpired:
            return {"ok": False, "output": "", "error": "timed out after %ds" % t}
        except FileNotFoundError:
            return {"ok": False, "output": "", "error": "shell not available"}
        out = (p.stdout or "")[-20000:]
        if (p.stderr or "").strip():
            out += "\n[stderr] " + (p.stderr or "")[-4000:]
        return {"ok": p.returncode == 0, "output": out,
                "error": "" if p.returncode == 0 else "exit %d" % p.returncode}

    def powershell(command: str = "", timeout: int = 3600, **kw) -> dict:
        c = command or kw.get("cmd") or kw.get("args") or ""
        if not c:
            return {"ok": False, "output": "", "error": "missing argument: command"}
        t = max(1, min(int(timeout or 3600), 86400))
        exe = "powershell" if _platform.system() == "Windows" else "pwsh"
        try:
            p = _subprocess.run([exe, "-NoProfile", "-Command", str(c)],
                                capture_output=True, text=True, timeout=t)
        except FileNotFoundError:
            return {"ok": False, "output": "", "error":
                    "PowerShell is not installed on this OS; the tool runs on Windows builds"}
        except _subprocess.TimeoutExpired:
            return {"ok": False, "output": "", "error": "timed out after %ds" % t}
        out = (p.stdout or "")[-20000:]
        if (p.stderr or "").strip():
            out += "\n[stderr] " + (p.stderr or "")[-4000:]
        return {"ok": p.returncode == 0, "output": out,
                "error": "" if p.returncode == 0 else "exit %d" % p.returncode}

    registry.register_tool("terminal", _schema(
        "Run a terminal command: bash on Linux, PowerShell on Windows. "
        "args: command, timeout (seconds, optional).",
        {"command": {"type": "string"},
         "timeout": {"type": "integer"}}, ["command"]), terminal)

    registry.register_tool("powershell", _schema(
        "Run a PowerShell command (pwsh on Linux, powershell.exe on Windows). "
        "args: command, timeout (seconds, optional).",
        {"command": {"type": "string"},
         "timeout": {"type": "integer"}}, ["command"]), powershell)

    import json as _json

    def rag_pass(name: str, a: dict) -> dict:
        from services import rag_mcp as _r
        try:
            r = _r.dispatch(name, a)
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _cap_json(r)), "error": ""}

    def rag_search(db: str = "", query: str = "", k: int = 5, **kw) -> dict:
        if not (db and query):
            return {"ok": False, "output": "", "error": "missing argument: db, query"}
        return rag_pass("rag_search", {"db": str(db), "query": str(query),
                                       "k": max(1, int(k or 5))})

    def rag_status(**kw) -> dict:
        return rag_pass("rag_status", {})

    registry.register_tool("rag_search", _schema(
        "Search a local knowledge base offline. args: db, query, k.",
        {"db": {"type": "string"}, "query": {"type": "string"},
         "k": {"type": "integer"}}, ["db", "query"]), rag_search)

    registry.register_tool("rag_status", _schema(
        "List local knowledge bases with record counts.", {}, []), rag_status)

    def rag_ingest_text(db: str = "", text: str = "", confirm: bool = False, **kw) -> dict:
        if not confirm:
            return {"ok": False, "output": "",
                    "error": "consent required: pass confirm=true to ingest"}
        # 2026-11-19: the model tried to paste whole documents into this tool
        # argument, which blew the output cap, so the call arrived truncated
        # and was refused. Refuse oversized text with the correct path.
        body = str(text or "")
        if len(body) > 8000:
            return {
                "ok": False,
                "output": "",
                "error": (
                    "text too large for a tool call (%d chars). Never paste "
                    "documents into tool arguments. Use greysearch or search to "
                    "find the page, then call rag_ingest_urls with its URL."
                    % len(body)
                ),
            }
        from services import rag_mcp as _r
        try:
            r = _r.dispatch("rag_ingest_text", {"db": str(db), "text": body})
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _json.dumps(r, default=str))[:20000], "error": ""}

    registry.register_tool("rag_ingest_text", _schema(
        "Ingest a SHORT note (max 8000 chars) into a knowledge base. For web "
        "pages use greysearch/search and then rag_ingest_urls. "
        "CONSENT-GATED: requires confirm=true. args: db, text, confirm.",
        {"db": {"type": "string"}, "text": {"type": "string"},
         "confirm": {"type": "boolean"}}, ["db", "text", "confirm"]), rag_ingest_text)

    from services import search_mcp as _sm

    def search(query: str = "", k: int = 5, **kw) -> dict:
        if not query:
            return {"ok": False, "output": "", "error": "missing argument: query"}
        # 2026-11-19: the plain search lane pointed at public SearXNG instances
        # that return nothing here (search_health was literally "0.0"), so every
        # "search this" got an empty list. The greysearch lane has working
        # direct backends (bing-rss / ddg-html); use it first, fall back to the
        # old client only if the deep lane fails outright.
        try:
            from core.greysearch import greysearch_mcp as _gs
            r = _gs.research_search(str(query), max_results=max(1, int(k or 5)))
        except Exception:
            try:
                r = _sm.search(str(query), max(1, int(k or 5)))
            except Exception as e:
                return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _json.dumps(r, default=str))[:20000], "error": ""}

    def search_health(**kw) -> dict:
        try:
            r = _sm.health_wait()
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _json.dumps(r, default=str))[:20000], "error": ""}

    registry.register_tool("search", _schema(
        "Quick web search over the local search lanes. args: query, k.",
        {"query": {"type": "string"}, "k": {"type": "integer"}}, ["query"]), search)

    registry.register_tool("search_health", _schema(
        "Check the search lane health.", {}, []), search_health)

    def greysearch_tool(query: str = "", max_results: int = 10, **kw) -> dict:
        from core.greysearch import greysearch_mcp as _gs
        if not query:
            return {"ok": False, "output": "", "error": "missing argument: query"}
        # 2026-11-19: the deep path is the product. It runs in a subprocess so a
        # wedged engine or browser can never hang the tool; on failure or
        # timeout the search lanes still answer. The browser page scraping and
        # the semantic judge stay in the deep path (they are what make it
        # research rather than a link list).
        import os as _os
        import subprocess as _sp
        import sys as _sys

        script = r'''
import json, os, socket, subprocess, sys
socket.setdefaulttimeout(15)
# Owner order 2026-11-19: any zombie/hung listener on a port this product uses
# is closed before the run, but the process this run launches is kept.
root = os.getcwd()
if os.name != "nt":
    subprocess.run([sys.executable, os.path.join(root, "scripts", "reap_hung_ports.py"),
                    "--slots", "--searx", "--apply"], cwd=root, timeout=180)
from core.greysearch import greysearch_mcp as g
q = sys.argv[1]
pages = int(sys.argv[2])
r = g.research_deep(q, max_pages=pages, max_total_seconds=240,
                    enable_semantic_judge=True, min_accept_score=35)
out = {k: r.get(k) for k in ("sources", "facts", "rejected_pages",
                             "quarantined_pages", "run_report", "budget_hit",
                             "judge_ran")}
try:
    r = g._attach_guide(r, q, g._resolve_guide_path(None, q))
    out["master_guide"] = {"path": (r.get("master_guide") or {}).get("path")}
except Exception as exc:
    out["guide_error"] = str(exc)[:200]
print("__GMA__" + json.dumps(out, default=str))
'''
        pages_wanted = max(1, min(int(max_results or 10), 2))
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        cwd = root if _os.path.isdir(_os.path.join(root, "core")) else _os.getcwd()
        try:
            proc = _sp.run(
                [_sys.executable, "-c", script, str(query), str(pages_wanted)],
                cwd=cwd, capture_output=True, text=True, timeout=300,
            )
            marker = "__GMA__"
            line = next(
                (ln for ln in (proc.stdout or "").splitlines() if ln.startswith(marker)),
                "",
            )
            if line:
                deep = _json.loads(line[len(marker):])
                sources = deep.get("sources") or []
                if sources:
                    payload = {
                        "mode": "deep",
                        "query": str(query),
                        "sources": sources,
                        "accepted": len(sources),
                        "facts": len(deep.get("facts") or []),
                        "guide": (deep.get("master_guide") or {}).get("path", ""),
                        "budget_hit": deep.get("budget_hit"),
                    }
                    return {"ok": True,
                            "output": _json.dumps(payload, default=str)[:40000],
                            "error": ""}
        except Exception:
            pass
        try:
            r = _gs.research_search(str(query), max_results=max(1, int(max_results or 10)))
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        results = (r or {}).get("results") or []
        payload = {
            "mode": "search-lanes",
            "query": str(query),
            "results": results,
            "note": "Deep scraping did not complete; these are ranked sources with snippets.",
        }
        return {"ok": True, "output": _json.dumps(payload, default=str)[:40000], "error": ""}

    def greysearch_health(**kw) -> dict:
        from core.greysearch import greysearch_mcp as _gs
        try:
            r = _gs.dispatch("greysearch_health", {})
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _json.dumps(r, default=str))[:20000], "error": ""}

    registry.register_tool("greysearch", _schema(
        "Deep web research: multi-lane search plus full-page scraping. "
        "args: query, max_results.",
        {"query": {"type": "string"},
         "max_results": {"type": "integer"}}, ["query"]), greysearch_tool)

    registry.register_tool("greysearch_health", _schema(
        "Check the deep research lanes.", {}, []), greysearch_health)

    def rag_pass(name: str, a: dict) -> dict:
        from services import rag_mcp as _r
        try:
            r = _r.dispatch(name, a)
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _cap_json(r)), "error": ""}

    def rag_ingest_pdf(db: str = "", path: str = "", confirm: bool = False, **kw) -> dict:
        if not confirm:
            return {"ok": False, "output": "",
                    "error": "consent required: pass confirm=true to ingest"}
        return rag_pass("rag_ingest_pdf", {"db": str(db), "paths": [str(path)]})

    def rag_ingest_urls(db: str = "", urls=None, confirm: bool = False, **kw) -> dict:
        if not confirm:
            return {"ok": False, "output": "",
                    "error": "consent required: pass confirm=true to ingest"}
        return rag_pass("rag_ingest_urls", {"db": str(db),
                                            "urls": list(urls or kw.get("url") or [])})

    def rag_remove(db: str = "", match: str = "", confirm: bool = False, **kw) -> dict:
        return rag_pass("rag_remove", {"db": str(db), "match": str(match),
                                       "confirm": bool(confirm)})

    def rag_list_sources(db: str = "", **kw) -> dict:
        return rag_pass("rag_list_sources", {"db": str(db)})

    registry.register_tool("rag_ingest_pdf", _schema(
        "Ingest a PDF into a knowledge base. CONSENT-GATED: confirm=true required. "
        "args: db, path, confirm.",
        {"db": {"type": "string"}, "path": {"type": "string"},
         "confirm": {"type": "boolean"}}, ["db", "path", "confirm"]), rag_ingest_pdf)

    registry.register_tool("rag_ingest_urls", _schema(
        "Ingest web pages into a knowledge base. CONSENT-GATED: confirm=true required. "
        "args: db, urls (list), confirm.",
        {"db": {"type": "string"},
         "urls": {"type": "array", "items": {"type": "string"}},
         "confirm": {"type": "boolean"}}, ["db", "urls", "confirm"]), rag_ingest_urls)

    registry.register_tool("rag_remove", _schema(
        "Two-step removal: first call previews matches, confirmed call deletes. "
        "args: db, match, confirm.",
        {"db": {"type": "string"}, "match": {"type": "string"},
         "confirm": {"type": "boolean"}}, ["db", "match"]), rag_remove)

    registry.register_tool("rag_list_sources", _schema(
        "List sources recorded in a knowledge base. args: db.",
        {"db": {"type": "string"}}, ["db"]), rag_list_sources)

    from pathlib import Path as _Path

    def skills_list(**kw) -> dict:
        root = _Path(__file__).resolve().parent.parent / ".superpowers"
        out = []
        if root.is_dir():
            for p in sorted(root.rglob("*.md")):
                out.append(str(p.relative_to(root)))
        return {"ok": True, "output": _json.dumps(out), "error": ""}

    def skill(name: str = "", **kw) -> dict:
        if not name:
            return {"ok": False, "output": "", "error": "missing argument: name"}
        root = _Path(__file__).resolve().parent.parent / ".superpowers"
        cands = [p for p in sorted(root.rglob("*.md"))
                 if name == p.stem or name in str(p.relative_to(root))]
        if not cands:
            return {"ok": False, "output": "",
                    "error": "no skill named %s; use skills_list" % name}
        try:
            return {"ok": True, "output": cands[0].read_text(
                encoding="utf-8")[:20000], "error": ""}
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}

    registry.register_tool("skills_list", _schema(
        "List the local skill library (methodology playbooks on disk).", {}, []), skills_list)

    registry.register_tool("skill", _schema(
        "Read one local skill playbook. args: name (see skills_list).",
        {"name": {"type": "string"}}, ["name"]), skill)

    from tools.document_adapter import parse_document as _parse_doc
    registry.register_tool("parse_document", _schema(
        "Parse doc. args: file",
        {"file": {"type": "string"}}, ["file"]), _parse_doc)

    import tools.charts as charts_mod

    def charts_tool(series: str = "", **kw) -> dict:
        # 2026-11-19: the old lambda looked for a render_series() that does not
        # exist, so it echoed its input. tools.charts has real renderers.
        import re as _re
        raw = str(series or "").strip()
        pairs = {}
        for part in raw.split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                try:
                    pairs[k.strip()] = float(v)
                except ValueError:
                    pass
        if pairs:
            return {"ok": True, "output": charts_mod.bar_chart(pairs), "error": ""}
        try:
            nums = [float(x) for x in _re.split(r"[,\s]+", raw) if x]
        except ValueError:
            nums = []
        if nums:
            fn = charts_mod.line_chart if len(nums) <= 40 else charts_mod.sparkline
            return {"ok": True, "output": fn(nums), "error": ""}
        return {"ok": False, "output": "",
                "error": "series must be numbers (1,2,3) or label:value pairs"}

    registry.register_tool("charts", _schema(
        "Render a text chart. args: series (numbers like 1,2,3 or label:value pairs)",
        {"series": {"type": "string"}}, ["series"]), charts_tool)

    # 2026-11-19 (owner: vision either fully works or is out): removed. The
    # vendored engine segfaults building the Qwen3-VL vision graph and the
    # shipped projector uses a fused patch tensor this loader does not split,
    # so the product ships the text model and offers no vision tool.

    def system_status(**kw) -> dict:
        from model.server import is_ready, server_url
        from core import llm as llm_mod
        return {"ok": True, "output": "model=%s tps=%.1f calls=%d" % (
            is_ready() and server_url() or "down", llm_mod.LAST_TPS,
            llm_mod.USAGE["calls"]), "error": ""}

    registry.register_tool("system", _schema(
        "Status.",
        {}, []), system_status)

    _state["done"] = True
    return len(registry.list_tools())
