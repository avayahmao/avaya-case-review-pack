import json
import sys
from pathlib import Path


def error_response(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def launch_context():
    return {
        "script_path": str(Path(__file__).resolve()),
        "cwd": str(Path.cwd().resolve()),
    }


def handle_request(request):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return error_response(request.get("id") if isinstance(request, dict) else None, -32600, "Invalid Request")

    params = request.get("params", {})
    if not isinstance(params, dict):
        return error_response(request.get("id"), -32600, "Invalid Request")

    method = request["method"]
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "relative-path-probe", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "report_launch_context",
                    "description": "Return the probe script path and current working directory.",
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                }
            ]
        }
    elif method == "tools/call":
        if params.get("name") != "report_launch_context":
            return error_response(request.get("id"), -32601, "Method not found")
        result = {"content": [{"type": "text", "text": json.dumps(launch_context())}], "structuredContent": launch_context()}
    else:
        return error_response(request.get("id"), -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def main():
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = error_response(None, -32600, "Invalid Request")
        else:
            response = handle_request(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
