from __future__ import annotations
import json
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
import creds_store
import exec_gate
import http_safe
import kali_bank
import py_sandbox
import scan_builders
import store
SERVER = {'name': 'greyteam', 'version': '1.0.0'}
PROTOCOL = '2024-11-05'

def _tool(name, description, params, required=None):
    return {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': params or {}, 'required': required or []}}

def _s(**kw):
    return {'type': 'string', **kw}

def _i(**kw):
    return {'type': 'integer', **kw}

def _o(**kw):
    return {'type': 'object', **kw}
TOOLS = [_tool('create_assessment', 'Create a GreyTeam assessment (name, scope, objectives). Gather scope BEFORE calling.', {'name': _s(), 'client_name': _s(), 'category': _s(), 'scope': _s(), 'objectives': _s(), 'ip_scopes': {'type': 'array', 'items': _s()}}, ['name']), _tool('load_assessment', 'Load an existing assessment.', {'name': _s()}, ['name']), _tool('list_assessments', 'List all assessments.', None), _tool('add_card', 'Add a finding/observation/info card. On FAIL findings supply a cvss_vector.', {'assessment': _s(), 'card_type': _s(), 'title': _s(), 'cvss_vector': _s(), 'detail': _o()}, ['assessment', 'card_type', 'title']), _tool('update_card', 'Update a card by id (status, detail).', {'card_id': _i(), 'status': _s(), 'detail': _o()}, ['card_id']), _tool('delete_card', 'Delete a card by id.', {'card_id': _i()}, ['card_id']), _tool('list_cards', 'List cards for an assessment.', {'assessment': _s(), 'card_type': _s()}, ['assessment']), _tool('add_recon_data', 'Record reconnaissance data (single or batch).', {'assessment': _s(), 'data_type': _s(), 'name': _s(), 'details': _o(), 'entries': {'type': 'array'}}, ['assessment']), _tool('list_recon', 'List recon entries (optional type filter).', {'assessment': _s(), 'data_type': _s()}, ['assessment']), _tool('credentials_add', 'Store a credential ENCRYPTED. Tool output never contains the value.', {'assessment': _s(), 'name': _s(), 'credential_type': _s(), 'value': _s(), 'target': _s(), 'notes': _s()}, ['assessment', 'name', 'credential_type', 'value']), _tool('credentials_list', 'List credentials as placeholders — never plaintext.', {'assessment': _s()}, ['assessment']), _tool('execute', 'Run an allowlisted binary as plain argv inside the GreyTeam workspace. No shell, no metacharacters, fail-closed.', {'command': _s(), 'timeout': _i()}, ['command']), _tool('python_exec', 'Run sandboxed python: import allowlist, no network, resource-capped, fail-closed.', {'code': _s(), 'timeout': _i()}, ['code']), _tool('http_request', 'SSRF-hardened HTTP from the box: policy-allowlisted hosts only; localhost/link-local/metadata are permanently blocked.', {'url': _s(), 'method': _s(), 'headers': _o(), 'timeout': _i()}, ['url']), _tool('scan', 'Build + run a scanner via the exec gate (argv templates; target metacharacters are refused).', {'scan_type': _s(), 'target': _s(), 'ports': _s(), 'wordlist': _s(), 'threads': _i(), 'timeout': _i()}, ['scan_type', 'target']), _tool('ssl_analysis', 'TLS cert analysis helper (openssl).', {'target': _s(), 'port': _i()}, ['target']), _tool('subdomain_enum', 'DNS-based subdomain probe (dig) — offline-first.', {'domain': _s()}, ['domain']), _tool('tech_detection', 'Fingerprint a web app (whatweb).', {'url': _s()}, ['url']), _tool('kali_bank', 'Read-only lookup in the lab-only Kali command bank: query, tool, phase 0-9, or slot {{VAR}}.', {'query': _s(), 'tool': _s(), 'phase': _s(), 'slot': _s(), 'limit': _i()}), _tool('list_asvs_requirements', 'List ASVS grid rows (status/chapter filter).', {'status': _s(), 'chapter': _s()}), _tool('get_asvs_summary', 'ASVS coverage summary (pass/remaining).', None), _tool('update_asvs_requirement', 'Record an ASVS verdict (PASS/FAIL/NA/NOT_TESTED) with analysis.', {'req_id': _s(), 'status': _s(), 'analysis': _s()}, ['req_id', 'status'])]

def handle(name: str, a: dict) -> dict:
    assessment = a.get('assessment') or a.get('name')
    if name == 'create_assessment':
        return store.create_assessment(a['name'], category=a.get('category', 'General'), scope=a.get('scope', ''), objectives=a.get('objectives', ''))
    if name == 'load_assessment':
        return store.load_assessment(a['name'])
    if name == 'list_assessments':
        return store.list_assessments()
    if name == 'add_card':
        return store.add_card(assessment, a.get('card_type'), a['title'], {'cvss': a.get('cvss_vector') or '', **(a.get('detail') or {})})
    if name == 'update_card':
        with store._lock, store._conn() as c:
            n = c.execute('UPDATE cards SET status=COALESCE(?,status), json=COALESCE(?,json) WHERE id=?', (a.get('status'), json.dumps(a['detail']) if a.get('detail') else None, a['card_id'])).rowcount
            if not n:
                return {'ok': False, 'error': f"no card {a['card_id']}"}
            return {'ok': True, 'note': f"card {a['card_id']} updated"}
    if name == 'delete_card':
        with store._lock, store._conn() as c:
            n = c.execute('DELETE FROM cards WHERE id=?', (a['card_id'],)).rowcount
            return {'ok': bool(n)} if n else {'ok': False, 'error': f"no card {a['card_id']}"}
    if name == 'list_cards':
        return {'ok': True, 'cards': store.list_cards(assessment)}
    if name == 'add_recon_data':
        entries = a.get('entries')
        if entries:
            for e in entries:
                store.add_recon(assessment, e.get('data_type', ''), e.get('name', ''), e.get('details'))
            return {'ok': True, 'note': f'{len(entries)} recon entries added'}
        return store.add_recon(assessment, a.get('data_type', ''), a.get('name', ''), a.get('details'))
    if name == 'list_recon':
        return {'ok': True, 'recon': store.list_recon(assessment, a.get('data_type'))}
    if name == 'credentials_add':
        return creds_store.add(a['name'], a.get('credential_type', 'custom'), a.get('value', ''), a.get('notes', ''))
    if name == 'credentials_list':
        return creds_store.list_creds()
    if name == 'execute':
        try:
            return exec_gate.run(a['command'], timeout=a.get('timeout'))
        except exec_gate.GateDeny as e:
            return {'ok': False, 'error': f'EXEC GATE: {e}'}
    if name == 'python_exec':
        try:
            return py_sandbox.run(a['code'], timeout=a.get('timeout') or 30)
        except py_sandbox.SandboxDeny as e:
            return {'ok': False, 'error': f'PY SANDBOX: {e}'}
    if name == 'http_request':
        try:
            return http_safe.fetch(a['url'], method=a.get('method', 'GET'), headers=a.get('headers') or {}, timeout=a.get('timeout') or 20)
        except http_safe.HttpDeny as e:
            return {'ok': False, 'error': f'HTTP GATE: {e}'}
    if name == 'scan':
        if not a.get('target'):
            return {'ok': False, 'error': 'SCAN GATE: target required'}
        try:
            argv = scan_builders.build_scan(a.get('scan_type', ''), a['target'], ports=a.get('ports'), wordlist=a.get('wordlist', 'common'), threads=a.get('threads') or 10)
            return exec_gate.run(argv, timeout=a.get('timeout'))
        except (ValueError, FileNotFoundError, exec_gate.GateDeny) as e:
            return {'ok': False, 'error': f'SCAN GATE: {e}'}
    if name == 'ssl_analysis':
        try:
            return exec_gate.run(scan_builders.build_ssl(a['target'], a.get('port') or 443), timeout=30)
        except exec_gate.GateDeny as e:
            return {'ok': False, 'error': f'SSL GATE: {e}'}
    if name == 'subdomain_enum':
        try:
            return exec_gate.run(scan_builders.build_dns(a['domain']), timeout=20)
        except exec_gate.GateDeny as e:
            return {'ok': False, 'error': f'DNS GATE: {e}'}
    if name == 'tech_detection':
        try:
            return exec_gate.run(scan_builders.build_whatweb(a['url']), timeout=30)
        except exec_gate.GateDeny as e:
            return {'ok': False, 'error': f'TECH GATE: {e}'}
    if name == 'kali_bank':
        return kali_bank.bank_query(query=a.get('query', ''), tool=a.get('tool', ''), phase=a.get('phase', ''), slot=a.get('slot', ''), limit=a.get('limit') or 6)
    if name == 'list_asvs_requirements':
        return {'ok': True, 'requirements': store.asvs_list(a.get('status'))}
    if name == 'get_asvs_summary':
        return store.asvs_summary()
    if name == 'update_asvs_requirement':
        return store.asvs_status(a['req_id'], a.get('status', ''), a.get('analysis', ''))
    return {'ok': False, 'error': f'unknown tool {name!r}'}

def dispatch(req: dict) -> dict:
    m = req.get('method', '')
    rid = req.get('id')
    if m == 'initialize':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': SERVER}}
    if m == 'notifications/initialized' or not rid:
        return {}
    if m == 'tools/list':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {'tools': TOOLS}}
    if m == 'tools/call':
        p = req.get('params') or {}
        try:
            r = handle(p.get('name', ''), p.get('arguments') or {})
            out = json.dumps({'ok': r.get('ok', False), **r})[:500000]
        except Exception as e:
            r = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
            out = json.dumps(r)
        return {'jsonrpc': '2.0', 'id': rid, 'result': {'content': [{'type': 'text', 'text': out}]}}
    if m == 'ping':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {}}
    return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': f'unknown method {m!r}'}}

def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'bad JSON'}}) + '\n')
        else:
            resp = dispatch(req)
            if resp:
                sys.stdout.write(json.dumps(resp) + '\n')
        sys.stdout.flush()
    return 0
if __name__ == '__main__':
    sys.exit(main())