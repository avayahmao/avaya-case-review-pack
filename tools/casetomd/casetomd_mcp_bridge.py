import sys
import json
import urllib.request
import ssl

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

CASE_TO_MD_URL = "https://192.168.67.160:8000/mcp"

def call_casetomd(report_id):
    ctx = ssl._create_unverified_context()
    
    try:
        # 1. Initialize session
        req1 = urllib.request.Request(
            CASE_TO_MD_URL,
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'initialize',
                'params': {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {},
                    'clientInfo': {'name': 'casetomd-bridge', 'version': '1.0'}
                },
                'id': 1
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        )
        resp1 = urllib.request.urlopen(req1, context=ctx, timeout=15)
        sess_id = resp1.headers.get('mcp-session-id')
        
        # 2. Call get_case_markdown tool
        req2 = urllib.request.Request(
            CASE_TO_MD_URL,
            data=json.dumps({
                'jsonrpc': '2.0',
                'method': 'tools/call',
                'params': {
                    'name': 'get_case_markdown',
                    'arguments': {'report_id': report_id}
                },
                'id': 2
            }).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/event-stream',
                'mcp-session-id': sess_id
            }
        )
        resp2 = urllib.request.urlopen(req2, context=ctx, timeout=30)
        lines = resp2.read().decode('utf-8').splitlines()
        for line in lines:
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    return data['result']
                if 'error' in data:
                    return {'error': data['error']}
        return {'error': 'No response data from CaseToMD'}
    except Exception as e:
        return {'error': f'Failed to connect to CaseToMD server at 192.168.67.160 ({str(e)}). Please verify Avaya corporate VPN connection.'}

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
            method = req.get('method')
            msg_id = req.get('id')
            
            if method == 'initialize':
                resp = {
                    'jsonrpc': '2.0',
                    'id': msg_id,
                    'result': {
                        'protocolVersion': '2024-11-05',
                        'capabilities': {'tools': {}},
                        'serverInfo': {'name': 'CaseToMD', 'version': '1.0'}
                    }
                }
            elif method == 'tools/list':
                resp = {
                    'jsonrpc': '2.0',
                    'id': msg_id,
                    'result': {
                        'tools': [{
                            'name': 'get_case_markdown',
                            'description': 'Fetch Siebel SR or ServiceNow INC markdown report',
                            'inputSchema': {
                                'type': 'object',
                                'properties': {
                                    'report_id': {'type': 'string', 'description': 'SR ID or INC ID'}
                                },
                                'required': ['report_id']
                            }
                        }]
                    }
                }
            elif method == 'tools/call':
                params = req.get('params', {})
                args = params.get('arguments', {})
                report_id = args.get('report_id', '')
                
                res = call_casetomd(report_id)
                resp = {
                    'jsonrpc': '2.0',
                    'id': msg_id,
                    'result': res if isinstance(res, dict) and 'content' in res else {
                        'content': [{'type': 'text', 'text': json.dumps(res, ensure_ascii=False)}]
                    }
                }
            elif method == 'notifications/initialized':
                continue
            else:
                resp = {
                    'jsonrpc': '2.0',
                    'id': msg_id,
                    'result': {}
                }
                
            sys.stdout.write(json.dumps(resp) + '\n')
            sys.stdout.flush()
        except Exception as e:
            err_resp = {
                'jsonrpc': '2.0',
                'id': req.get('id') if 'req' in locals() else None,
                'error': {'code': -32603, 'message': str(e)}
            }
            sys.stdout.write(json.dumps(err_resp) + '\n')
            sys.stdout.flush()

if __name__ == '__main__':
    main()
