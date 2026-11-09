"""One bounded OpenRouter request, in a child of the otherwise offline harness.

stdin/stdout are private IPC. Never log prompts, keys, raw HTTP bodies or reasoning.
The child can contact only the fixed inference endpoint; no application DB is loaded.
"""
import json,os,sys,time,math
import httpx

MODEL='openai/gpt-4o-mini'
ENDPOINT='https://openrouter.ai/api/v1/chat/completions'
MAX_BYTES=64000
MAX_OUTPUT=2048

class ProbeHTTPError(RuntimeError):
    def __init__(self,status):self.status=status;super().__init__('OpenRouterHTTP'+str(status))


def payload(request):
    if request.get('model')!=MODEL:raise ValueError('Evaluation model must remain openai/gpt-4o-mini')
    messages=request['messages'];schema=request['schema']
    if not isinstance(messages,list) or not messages or any(m.get('role') not in {'system','user','assistant'} or not isinstance(m.get('content'),str) for m in messages):raise ValueError('Invalid evaluation messages')
    if len(json.dumps(request,ensure_ascii=False).encode())>MAX_BYTES:raise ValueError('Evaluation request exceeds 64 KB')
    return {'model':MODEL,'messages':messages,'temperature':.2,'max_tokens':MAX_OUTPUT,'stream':False,
        'response_format':{'type':'json_schema','json_schema':{'name':'sales_evaluation','strict':True,'schema':schema}},
        'provider':{'require_parameters':True,'allow_fallbacks':False,'max_price':{'prompt':1,'completion':2,'request':0}}}


def probe(request,key,*,transport=None):
    body=payload(request)
    if not key:raise ValueError('OPENROUTER_API_KEY missing')
    started=time.monotonic()
    with httpx.Client(timeout=18,follow_redirects=False,transport=transport) as client:
        with client.stream('POST',ENDPOINT,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=body) as response:
            if response.status_code!=200:raise ProbeHTTPError(response.status_code)
            chunks=[];size=0
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>256000:raise ValueError('Oversized inference response')
                chunks.append(chunk)
    data=json.loads(b''.join(chunks));choice=data['choices'][0]
    if choice.get('finish_reason')!='stop':raise ValueError('Incomplete inference response')
    text=choice['message']['content']
    if not isinstance(text,str) or len(text.encode())>16000:raise ValueError('Invalid inference content')
    observed=data.get('model','')
    if not observed.startswith(MODEL):raise ValueError('Unexpected inference model')
    usage=data.get('usage') or {}
    cost=usage.get('cost')
    if cost is not None and (isinstance(cost,bool) or not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0):raise ValueError('Invalid provider usage cost')
    tokens={k:usage.get(k) if type(usage.get(k)) is int and usage[k]>=0 else None for k in ['prompt_tokens','completion_tokens']}
    return {'text':text,'model':observed,'usage':{**tokens,'cost':cost},'elapsed_ms':round((time.monotonic()-started)*1000)}


def main():
    try:
        raw=sys.stdin.buffer.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError('Oversized request')
        result=probe(json.loads(raw),os.environ.get('OPENROUTER_API_KEY'))
    except Exception as exc:
        # Class/code only: exception messages may contain a key, body or proxy URL.
        result={'error':type(exc).__name__}
        if isinstance(exc,ProbeHTTPError):result['http_status']=exc.status
    sys.stdout.write(json.dumps(result,ensure_ascii=False))
    return 1 if 'error' in result else 0


if __name__=='__main__':raise SystemExit(main())
