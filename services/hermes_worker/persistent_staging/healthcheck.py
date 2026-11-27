"""Keep the real readiness contract; emit status without response bodies."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from startup_evidence import event


def check():
    try:
        with urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=3) as response:
            value=json.loads(response.read(8192))
            if response.status!=200 or value.get('status')!='ready':
                event('health_http','FAIL',reason='unexpected_response',http_status=response.status);return 1
        event('health_http','PASS',http_status=200);return 0
    except HTTPError as exc:
        reason='http_error'
        try:
            detail=json.loads(exc.read(8192)).get('detail',{})
            if isinstance(detail,dict) and isinstance(detail.get('reason'),str) and detail.get('reason') in {'database_unavailable','schema_incompatible'}:reason=detail['reason']
        except (ValueError,TypeError,AttributeError):pass
        event('health_http','FAIL',reason=reason,http_status=exc.code);return 1
    except (URLError,TimeoutError,OSError):
        event('health_http','FAIL',reason='connection_error');return 1
    except (ValueError,TypeError,AttributeError):
        event('health_http','FAIL',reason='unexpected_response');return 1

if __name__=='__main__':raise SystemExit(check())
