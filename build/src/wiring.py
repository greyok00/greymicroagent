from __future__ import annotations

from core import registry
from core.registry import _schema

_state = {"done": False}


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
        from tools.research_integration import research_scrape
        u = url or kw.get("uri") or kw.get("page")
        if not u:
            return {"ok": False, "output": "", "error": "missing argument: url"}
        r = research_scrape(u, max_chars=max_chars)
        r.setdefault("trust", "high")
        return r

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
    from services.rag import kbcore as _kb

    def rag_search(db: str = "", query: str = "", k: int = 5, **kw) -> dict:
        if not (db and query):
            return {"ok": False, "output": "", "error": "missing argument: db, query"}
        try:
            hits = _kb.search(_kb.db_dir(str(db)), str(query), max(1, int(k or 5)))
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": str(hits)[:20000], "error": ""}

    def rag_status(**kw) -> dict:
        try:
            return {"ok": True, "output": _json.dumps(_kb.dbs()), "error": ""}
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}

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
        from services import rag_mcp as _r
        try:
            r = _r.dispatch("rag_ingest_text", {"db": str(db), "text": str(text)})
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _json.dumps(r, default=str))[:20000], "error": ""}

    registry.register_tool("rag_ingest_text", _schema(
        "Ingest text into a knowledge base. CONSENT-GATED: requires confirm=true. "
        "args: db, text, confirm.",
        {"db": {"type": "string"}, "text": {"type": "string"},
         "confirm": {"type": "boolean"}}, ["db", "text", "confirm"]), rag_ingest_text)

    from services import search_mcp as _sm

    def search(query: str = "", k: int = 5, **kw) -> dict:
        if not query:
            return {"ok": False, "output": "", "error": "missing argument: query"}
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
        try:
            r = _gs.dispatch("greysearch", {"query": str(query),
                                            "max_results": int(max_results or 10)})
        except Exception as e:
            return {"ok": False, "output": "", "error": str(e)[:400]}
        return {"ok": True, "output": (r if isinstance(r, str)
                                       else _json.dumps(r, default=str))[:40000], "error": ""}

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
                                       else _json.dumps(r, default=str))[:40000], "error": ""}

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
    registry.register_tool("charts", _schema(
        "Chart data. args: series",
        {"series": {"type": "string"}}, ["series"]),
        lambda series, **kw: {"ok": True, "output": str(
            getattr(charts_mod, "render_series", None)(series)
            if hasattr(charts_mod, "render_series") else series), "error": ""})

    def vision(image_path: str = "", question: str = "Describe this image.", **kw) -> dict:
        import base64
        from core.llm import _post
        img = image_path or kw.get("image") or kw.get("file")
        p = _safe_img(img)
        if p is None:
            return {"ok": False, "output": "", "error": "missing or bad image path"}
        b64 = base64.b64encode(p.read_bytes()).decode()
        data = _post({"model": "qwen3.8-27b",
                      "messages": [{"role": "user", "content": [
                          {"type": "text", "text": question},
                          {"type": "image_url",
                           "image_url": {"url": "data:image;base64," + b64}}]}],
                      "max_tokens": 512, "stream": False}, 120)
        if not data:
            return {"ok": False, "output": "", "error": "vision unavailable"}
        return {"ok": True, "output": data["choices"][0]["message"]["content"],
                "error": ""}

    def _safe_img(path: str):
        from pathlib import Path as _Path
        p = _Path(path).expanduser()
        if not p.is_absolute():
            p = _Path(__file__).resolve().parent.parent / p
        if p.exists() and p.suffix.lower() in (".png", ".jpg", ".jpeg",
                                               ".webp", ".gif"):
            return p
        return None

    registry.register_tool("vision", _schema(
        "Vision. args: image_path",
        {"image_path": {"type": "string"}}, ["image_path"]), vision)

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
