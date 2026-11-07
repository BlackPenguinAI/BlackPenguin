import '@angular/compiler';
import { describe,it,expect,vi } from 'vitest';
import { throwError,of,Subject } from 'rxjs';
import { OnboardingResponseOptionsComponent as Options } from '../shared/ui/onboarding-response-options/onboarding-response-options';
import { ChatComponent } from './chat/chat';
import { ProjectChatComponent } from './client/projects/project-chat/project-chat';

function options(){const c=new Options();c.question={field:'compliance_notes',label:'Compliance',prompt:'Choose',input_type:'multi_select',options:['Financing disclaimer','Provide later'],examples:[],allow_custom:true,minimum_words:null,detail_options:['Financing disclaimer'],answer_actions:{'Provide later':{kind:'defer'}}};return c;}
describe('Onboarding follow-up drafts and forms',()=>{
  it('requires concrete compliance instructions but allows incomplete deferral',()=>{
    const c=options(),answer=vi.fn(),defer=vi.fn();c.selected.subscribe(answer);c.deferred.subscribe(defer);
    c.choose('Financing disclaimer');c.submitSelection();expect(answer).not.toHaveBeenCalled();
    c.choose('Provide later');expect(defer).toHaveBeenCalledWith(['Financing disclaimer']);expect(c.selectedValues.size).toBe(1);
    c.optionDetails['Financing disclaimer']='Subject to lender approval.';c.submitSelection();expect(answer).toHaveBeenCalledWith(['Financing disclaimer: Subject to lender approval.']);
  });
  it('restores category and exact text without emitting or duplicating chips',()=>{
    const c=options();c.question.selected_values=['Financing disclaimer: Subject to lender approval.'];const emit=vi.fn();c.selected.subscribe(emit);c.ngOnChanges();
    expect(c.selectedValues.has('Financing disclaimer')).toBe(true);expect(c.optionDetails['Financing disclaimer']).toBe('Subject to lender approval.');
    expect(c.choices.filter(value=>value.startsWith('Financing disclaimer'))).toHaveLength(1);expect(emit).not.toHaveBeenCalled();
  });
  it('keeps a failed selection save recoverable in Project',()=>{
    const api={deferSelection:vi.fn(()=>throwError(()=>new Error('offline')))};
    const c=new ProjectChatComponent({} as never,api as never,{detectChanges:vi.fn()} as never,{} as never,{} as never);c.projectId='p';
    c.deferSelection(['Cash'],{id:'q',ui_payload:{field:'payment_methods'}} as any);
    expect(api.deferSelection).toHaveBeenCalledWith('p','payment_methods','q',['Cash']);expect(c.isAnalyzing).toBe(false);expect(c.errorMessage).toContain('choices remain');
  });
  it('reuses the detail request identity after timeout without losing entries',()=>{
    vi.useFakeTimers();
    try {
      const api={saveDetails:vi.fn((_id:string,_payload:any)=>new Subject())};const c=new ProjectChatComponent({} as never,api as never,{detectChanges:vi.fn()} as never,{} as never,{} as never);c.projectId='p';
      const value={field:'delivery_dates',deliveries:[{scope:'project',timing:'2026-12'}]};const question={id:'q'} as any;
      c.saveProjectDetails(value,question);vi.advanceTimersByTime(20001);expect(c.isAnalyzing).toBe(false);
      c.saveProjectDetails(value,question);
      expect(api.saveDetails.mock.calls[0][1].client_message_id).toBe(api.saveDetails.mock.calls[1][1].client_message_id);
      vi.advanceTimersByTime(20001);
    } finally {vi.useRealTimers();}
  });
  it('can continue Company public presence without adding another contact',()=>{
    const api={continuePublicPresence:vi.fn(()=>of({fields:[]}))};const c=Object.create(ChatComponent.prototype) as ChatComponent;
    Object.assign(c,{onboarding:api,currentStage:'enrichment',publicPresenceSaving:false,publicPresenceDirty:new Set(),publicPresenceEditing:new Set(),profile:{fields:[{key:'public_contact_phones',status:'confirmed'},{key:'corporate_social_profiles',status:'confirmed'}]},publicEmails:'',publicPhones:'+13055550100',socialProfiles:'https://example.com/company',cdr:{detectChanges:vi.fn()},syncState:vi.fn(),applyState:vi.fn(),scrollToBottom:vi.fn()});
    expect(c.canKeepConfirmedChannels).toBe(true);c.keepConfirmedChannels();expect(api.continuePublicPresence).toHaveBeenCalledOnce();
  });
});
