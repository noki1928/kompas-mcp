"""Structured errors and bounded JSONL audit log, never MCP stdout."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


def tool_result(result):
    """One failure shape for every tool: success=false becomes protocol isError with the
    same JSON in text and structuredContent. Other results pass through unchanged."""
    if not (isinstance(result, dict) and result.get('success') is False):
        return result
    from mcp.types import CallToolResult, TextContent
    return CallToolResult(isError=True, structuredContent=result,
                          content=[TextContent(type='text', text=json.dumps(result, ensure_ascii=False, default=str))])


def error_info(exc, method=None, object_id=None):
    hresult = getattr(exc, 'hresult', None)
    excepinfo = getattr(exc, 'excepinfo', None)
    return {'success': False, 'error_type': type(exc).__name__, 'message': str(exc),
            'api_method': method, 'api_error_code': hresult,
            'api_error_hex': f'0x{hresult & 0xffffffff:08X}' if isinstance(hresult, int) else None,
            'com_details': list(excepinfo) if excepinfo else None,
            'argument_error': getattr(exc, 'argerror', None), 'object_id': object_id,
            'cad_stage':getattr(exc,'cad_stage',None),
            'suggested_actions': ['Inspect describe_object / sdk_catalog for the exact signature',
                                  'Refresh document state and reacquire stale topology handles',
                                  'Check active document type and sketch editing state']}


class AuditLog:
    def __init__(self):
        self.path = Path(os.getenv('KOMPAS_LOG_PATH', str(Path(__file__).parent / 'artifacts' / 'actions.jsonl')))
        self.debug = os.getenv('KOMPAS_DEBUG') == '1'

    def record(self, tool, arguments, result=None, error=None, document=None, elapsed=None):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Limit large scripts, geometry arrays and base64 from accidental leakage.
            args = dict(arguments)
            if 'code' in args and not self.debug:
                args['code'] = f'<script length={len(args["code"])}; enable KOMPAS_DEBUG for contents>'
            row = {'timestamp': datetime.now(timezone.utc).isoformat(), 'tool': tool,
                   'arguments': args, 'document': document, 'elapsed_seconds': elapsed,
                   'result': result, 'errors': error}
            text = json.dumps(row, ensure_ascii=False, default=str)
            if len(text) > 100000:
                row['result'] = '<large result omitted>'
                text = json.dumps(row, ensure_ascii=False, default=str)
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(text + '\n')
        except Exception:
            # Logging failure must not turn a completed CAD mutation into a retry.
            import logging
            logging.getLogger(__name__).exception('Cannot write CAD audit log')
