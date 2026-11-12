import '@angular/compiler';
import { describe, expect, it, vi, afterEach } from 'vitest';
import { of, EMPTY } from 'rxjs';
import { ChatComponent } from './chat/chat';
import { EMPTY_COMPANY_PROFILE } from './chat/company-onboarding.models';

afterEach(() => vi.unstubAllGlobals());
describe('Company final approval journey', () => {
  it.each([true, false])('binds the approval card and navigates only on completion=%s', (completed) => {
    vi.stubGlobal('localStorage', { getItem: () => 'en' });
    const profile = { ...EMPTY_COMPANY_PROFILE, completion: { ...EMPTY_COMPANY_PROFILE.completion, can_complete: completed, final_approved: completed } };
    const send = vi.fn(() => of({ user_message: { id: 'user-1', sender: 'user', content: 'Approve profile', created_at: new Date(), attachments: [] }, message: { id: 'reply-1', sender: 'ai', content: completed ? 'Approved successfully' : 'Profile has blockers', created_at: new Date(), attachments: [] }, profile, next_question: null, sources: [], field_update_status: completed ? 'accepted' : 'rejected' }));
    const navigate = vi.fn();
    const component = new ChatComponent({ use: vi.fn() } as never, { sendMessage: send } as never, { detectChanges: vi.fn() } as never, { isSupported: false } as never, { navigateByUrl: navigate } as never);
    vi.spyOn(component as any, 'syncState').mockImplementation(() => undefined);
    vi.spyOn(component as any, 'scrollToBottom').mockImplementation(() => undefined);
    component.profile = { ...EMPTY_COMPANY_PROFILE };
    const card = { id: 'current-approval', sender: 'ai', content: 'Review', created_at: new Date(), attachments: [], ui_payload: { field: null, input_type: 'boolean', options: ['Approve profile'], answer_actions: { 'Approve profile': { kind: 'approve_profile' } } } };
    component.messages = [card as never];
    component.chooseAnswer('Approve profile', card as never);
    expect(send).toHaveBeenCalledWith('Approve profile', 'current-approval');
    expect(component.isCompleted).toBe(completed);
    if (completed) expect(navigate).toHaveBeenCalledWith('/app/company');
    else expect(navigate).not.toHaveBeenCalled();
    expect(component.isAnalyzing).toBe(false);
  });
});


describe('Company sidebar navigation', () => {
  it('opens review without binding the current approval card or approving it', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'en' });
    const send = vi.fn(() => EMPTY);
    const component = new ChatComponent({use:vi.fn()} as never,{sendMessage:send} as never,{detectChanges:vi.fn()} as never,{isSupported:false} as never,{} as never);
    vi.spyOn(component as any,'scrollToBottom').mockImplementation(() => undefined);
    component.messages=[{id:'approval',sender:'ai',content:'Review',created_at:new Date(),attachments:[],ui_payload:{field:null,input_type:'boolean',options:['Approve profile']}} as never];
    component.openCompanyTask('review');
    expect(send).toHaveBeenCalledWith('I want to review profile',null);
    expect(component.isCompleted).toBe(false);
  });
});
