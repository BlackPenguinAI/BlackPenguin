import '@angular/compiler';
import { of,Subject,throwError } from 'rxjs';
import { describe,it,expect,vi,afterEach } from 'vitest';
import { AgentContextComponent } from './agent-context';

afterEach(()=>vi.useRealTimers());
describe('Operational context',()=>{
  it('clears old state and ignores late responses after selecting another conversation',()=>{
    vi.useFakeTimers();const a=new Subject<any>(),b=new Subject<any>();let count=0;
    const component=new AgentContextComponent({get:vi.fn(()=>++count===1?a:b)} as any);
    component.conversationId='a';component.ngOnChanges();expect(component.loading).toBe(true);
    component.conversationId='b';component.ngOnChanges();a.next({current_interest:{property:'Wrong'}});b.next({current_interest:{property:'Correct'}});
    expect(component.data.current_interest.property).toBe('Correct');expect(component.loading).toBe(false);component.ngOnDestroy();
  });
  it('shows a diagnostic error and can refresh after a failed request',()=>{
    vi.useFakeTimers();const get=vi.fn().mockReturnValueOnce(throwError(()=>new Error('HTTP failed'))).mockReturnValue(of({chat:{status:'open'}}));
    const component=new AgentContextComponent({get} as any);component.conversationId='c';component.ngOnChanges();expect(component.error).toContain('could not be loaded');
    component.refresh();expect(component.data.chat.status).toBe('open');expect(component.error).toBe('');component.ngOnDestroy();
  });
  it('does not expose retries for restricted or read only context',()=>{
    const component=new AgentContextComponent({} as any);component.conversationId='c';component.data={scope_limited:true};component.canManage=true;
    expect(component.canRetry({status:'review'})).toBe(false);component.data={scope_limited:false};component.canManage=false;expect(component.canRetry({status:'review'})).toBe(false);
  });
  it('requires an explanation and uses the owning replacement operation',()=>{
    vi.useFakeTimers();const post=vi.fn(()=>of({status:'queued_for_recheck'})),get=vi.fn(()=>of({scope_limited:false}));
    const component=new AgentContextComponent({get,post} as any);component.conversationId='c';component.canManage=true;component.ngOnChanges();
    component.retry({id:'op',kind:'replacement_calendar',status:'review'});expect(post).not.toHaveBeenCalled();
    component.note='Reviewed provider binding';component.retry({id:'op',kind:'replacement_calendar',status:'review'});
    expect(post).toHaveBeenCalledWith(expect.stringContaining('/conversations/c/effects/retry'),{kind:'replacement',operation_id:'op',note:'Reviewed provider binding'});
    expect(component.notice).toContain('does not mean synchronization has succeeded');component.ngOnDestroy();
  });
  it('uses the meeting endpoint for Schedule and makes timestamps explicitly UTC',()=>{
    vi.useFakeTimers();const get=vi.fn(()=>of({scope_limited:true}));const component=new AgentContextComponent({get} as any);component.meetingId='m';component.ngOnChanges();
    expect(get).toHaveBeenCalledWith(expect.stringContaining('/meetings/m/operational-context'));
    expect(component.utc('2026-11-08T20:00:00')).toBe('2026-11-08T20:00:00Z');expect(component.utc('2026-11-08T20:00:00-05:00')).toContain('-05:00');component.ngOnDestroy();
  });
});
