import '@angular/compiler';
import { of, Subject, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { EngineStatus, SalesEngineControlComponent } from './sales-engine-control';
import { HermesSalesSettingsComponent } from '../hermes-sales/hermes-sales';

const status = (patch: Partial<EngineStatus> = {}): EngineStatus => ({
  active_sales_engine:'langgraph',effective_sales_engine:'langgraph',target_default_engine:'hermes',
  hermes_live_ready:false,available_engines:['langgraph'],selectable_engines:['langgraph'],automatic_fallback:false,error_code:null,
  published_version_id:'policy-1',published_policy_version:1,revision:1,hermes_policy_published:true,
  hermes_policy_valid:true,hermes_policy_enabled:true,hermes_policy_model:'openai/gpt-4o-mini',...patch,
});
const future = () => status({hermes_live_ready:true,available_engines:['langgraph','hermes'],selectable_engines:['langgraph','hermes']});
const cdr = () => ({markForCheck:vi.fn()}) as any;
function mount(value: EngineStatus = status()) {
  const get = vi.fn(()=>of(value)); const put = vi.fn((_url:string, body:{active_sales_engine:'hermes'|'langgraph'})=>of({...value,active_sales_engine:body.active_sales_engine,effective_sales_engine:body.active_sales_engine}));
  const c = new SalesEngineControlComponent({get,put} as any,cdr());c.ngOnInit();return {c,get,put};
}
function authorize(c: SalesEngineControlComponent, engine: 'hermes'|'langgraph'='hermes') {
  c.choose(engine); c.note='Reviewed global cutover';c.confirmed=true;
}

describe('HEI-05 global routing control',()=>{
  it('does not treat enabled policy as live activation',()=>{
    const {c,put}=mount();authorize(c);c.apply();
    expect(c.pending).toBeNull();expect(c.canSelect('hermes')).toBe(false);expect(put).not.toHaveBeenCalled();
  });
  it('requires a note and an explicit confirmation, and sends the reviewed snapshot',()=>{
    const {c,put}=mount(future());c.choose('hermes');c.apply();expect(put).not.toHaveBeenCalled();
    c.note='Reviewed';c.apply();expect(put).not.toHaveBeenCalled();c.confirmed=true;c.apply();
    expect(put).toHaveBeenCalledTimes(1);expect(put).toHaveBeenCalledWith(expect.stringContaining('/ai/hermes/engine'),{
      active_sales_engine:'hermes',change_note:'Reviewed',expected_revision:1,expected_published_version_id:'policy-1'});
    expect(c.status?.active_sales_engine).toBe('hermes');expect(c.pending).toBeNull();
  });
  it('requires a valid enabled publication in addition to readiness',()=>{
    const {c,put}=mount({...future(),hermes_policy_enabled:false});authorize(c);c.apply();expect(put).not.toHaveBeenCalled();
  });
  it('allows explicit recovery of invalid routing to LangGraph',()=>{
    const {c,put}=mount(status({active_sales_engine:null,effective_sales_engine:null,error_code:'INVALID_ENGINE_SELECTION'}));
    authorize(c,'langgraph');c.apply();expect(put).toHaveBeenCalledWith(expect.any(String),expect.objectContaining({active_sales_engine:'langgraph'}));
  });
  it('clears review state on stale response and never retries the PUT',()=>{
    const get=vi.fn().mockReturnValueOnce(of(future())).mockReturnValueOnce(of(status({revision:2})));
    const put=vi.fn(()=>throwError(()=>({error:{detail:{code:'ENGINE_SELECTION_STALE'}}})));
    const c=new SalesEngineControlComponent({get,put} as any,cdr());c.ngOnInit();authorize(c);c.apply();
    expect(put).toHaveBeenCalledTimes(1);expect(get).toHaveBeenCalledTimes(2);expect(c.status?.revision).toBe(2);
    expect(c.error).toContain('changed');expect(c.pending).toBeNull();expect(c.confirmed).toBe(false);
  });
  it('fails closed if the status request fails or the editor is busy',()=>{
    const put=vi.fn();const c=new SalesEngineControlComponent({get:vi.fn(()=>throwError(()=>new Error('403'))),put} as any,cdr());
    c.ngOnInit();authorize(c);c.apply();expect(c.status).toBeNull();expect(put).not.toHaveBeenCalled();
    const m=mount(future());authorize(m.c);m.c.locked=true;m.c.apply();expect(m.put).not.toHaveBeenCalled();
  });
  it('ignores late responses after reload or destruction',()=>{
    const a=new Subject<EngineStatus>(),b=new Subject<EngineStatus>();const c=new SalesEngineControlComponent({get:vi.fn().mockReturnValueOnce(a).mockReturnValueOnce(b)} as any,cdr());
    c.ngOnInit();c.load();a.next(future());expect(c.status).toBeNull();b.next(status());expect(c.status?.active_sales_engine).toBe('langgraph');c.ngOnDestroy();b.next(future());expect(c.status?.hermes_live_ready).toBe(false);
  });
});

describe('independent Hermes editor',()=>{
  const policy=()=>({engine:'hermes-agent',provider:'openrouter',language:'en',model:'openai/gpt-4o-mini',allowed_models:['openai/gpt-4o-mini'],system_prompt:'Verified property details. '.repeat(8),max_iterations:12,enabled_tools:['search_properties'],enabled:true});
  function editor(){
    const get=vi.fn((url:string)=>url.endsWith('/global')?of({configuration:policy(),available_tools:['search_properties'],published_version_id:'policy-1'}):of({items:[]}));
    const post=vi.fn((_url:string,_body:unknown)=>of({id:'draft-2',version:2}));const put=vi.fn();const c=new HermesSalesSettingsComponent({get,post,put} as any,cdr());c.ngOnInit();return {c,get,post,put};
  }
  it('keeps unsaved Hermes edits when routing changes',()=>{
    const {c}=editor();c.config!.max_iterations=4;c.onSelectionChanged(status({published_version_id:'switch-2'}));
    expect(c.config?.max_iterations).toBe(4);expect(c.publishedVersionId).toBe('switch-2');
  });
  it('saves a policy draft without invoking the selector',()=>{
    const {c,post,put}=editor();c.changeNote='new prompt';c.save(false);
    expect(post).toHaveBeenCalledTimes(1);expect(post).toHaveBeenCalledWith(expect.stringContaining('/ai/hermes/drafts'),expect.objectContaining({change_note:'new prompt'}));
    expect(put).not.toHaveBeenCalled();expect(c.notice).toContain('Routing unchanged');
  });
  it('publishes and reloads policy without invoking the selector',()=>{
    const {c,post,put}=editor();c.changeNote='approved prompt';c.save(true);
    expect(post).toHaveBeenCalledTimes(2);expect(post.mock.calls[1][0]).toContain('/versions/draft-2/publish');
    expect(put).not.toHaveBeenCalled();expect(c.notice).toContain('Engine selection unchanged');
  });
});
