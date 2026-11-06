import '@angular/compiler';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, HttpErrorResponse } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Subject } from 'rxjs';
import { ChatComponent } from './chat/chat';
import { CompanyOnboardingService } from './chat/company-onboarding.service';
import { ProjectChatComponent } from './client/projects/project-chat/project-chat';
import { ProjectOnboardingService } from './client/projects/project-chat/project-onboarding.service';
import { OnboardingResponseOptionsComponent as Options } from '../shared/ui/onboarding-response-options/onboarding-response-options';

const values=['Bank financing, subject to approval','Cash; staged payments by agreement'];
afterEach(()=>{vi.restoreAllMocks();TestBed.resetTestingModule();});

function project(api:any) {
 const c=new ProjectChatComponent({} as never,api,{detectChanges:vi.fn()} as never,{isSupported:false} as never,{} as never);
 c.projectId='p';vi.spyOn(c,'canSend','get').mockReturnValue(true);vi.spyOn(c as any,'scrollToBottom').mockImplementation(()=>{});vi.spyOn(c as any,'applyTurn').mockImplementation(()=>{});return c;
}
function company(api:any) {
 const c=new ChatComponent({use:vi.fn()} as never,api,{detectChanges:vi.fn()} as never,{isSupported:false} as never,{} as never);
 vi.spyOn(c,'canSend','get').mockReturnValue(true);vi.spyOn(c as any,'scrollToBottom').mockImplementation(()=>{});vi.spyOn(c as any,'applyTurn').mockImplementation(()=>{});return c;
}

describe('Lossless onboarding selection transport',()=>{
 it('emits the selected list, retaining punctuation in each element',()=>{
  const c=new Options();c.question={field:'payment_methods',label:'Payment',prompt:'Review',input_type:'multi_select',options:['Cash'],examples:[],allow_custom:true,minimum_words:null,selected_values:values};
  const emitted=vi.fn();c.selected.subscribe(emitted);c.ngOnChanges();c.submitSelection();expect(emitted).toHaveBeenCalledWith(values);
 });
 it.each(['company','project'])('sends a JSON array through the %s HTTP client',(scope)=>{
  TestBed.configureTestingModule({providers:[provideHttpClient(),provideHttpClientTesting()]});const http=TestBed.inject(HttpTestingController);
  if(scope==='company')TestBed.inject(CompanyOnboardingService).sendMessage(values.join('; '),'q',values).subscribe();
  else TestBed.inject(ProjectOnboardingService).sendMessage('p',values.join('; '),'q','client-id',values).subscribe();
  const request=http.expectOne(r=>r.url.endsWith('/chat'));expect(request.request.body.selected_values).toEqual(values);expect(request.request.body.in_reply_to_message_id).toBe('q');request.flush({});http.verify();
 });
 it('retains the exact Project selection and message id after a recoverable failed send',()=>{
  const first=new Subject<any>(),second=new Subject<any>();const api={sendMessage:vi.fn().mockReturnValueOnce(first).mockReturnValueOnce(second)};const c=project(api);
  c.chooseAnswer(values,{id:'q'} as never);const id=api.sendMessage.mock.calls[0][3];expect(api.sendMessage.mock.calls[0][4]).toEqual(values);
  first.error(new HttpErrorResponse({status:422,error:{detail:'Retry'}}));expect(c.prompt).toBe(values.join('; '));c.sendMessage();expect(api.sendMessage.mock.calls[1][3]).toBe(id);expect(api.sendMessage.mock.calls[1][4]).toEqual(values);
 });
 it('does not carry stale structured values when the Project text is manually changed',()=>{
  const first=new Subject<any>(),api={sendMessage:vi.fn().mockReturnValue(first)};const c=project(api);c.chooseAnswer(values,{id:'q'} as never);first.error(new HttpErrorResponse({status:422}));c.prompt='A different answer';c.sendMessage();expect(api.sendMessage.mock.calls[1]).toHaveLength(4);
 });
 it('does not silently send a selection through the file-only ingestion path',()=>{
  const api={sendMessage:vi.fn().mockReturnValue(new Subject()),sendMessageWithFiles:vi.fn()};const c=project(api);c.selectedFiles=[new File(['x'],'x.pdf')];c.chooseAnswer(values,{id:'q'} as never);
  expect(api.sendMessage).not.toHaveBeenCalled();expect(api.sendMessageWithFiles).not.toHaveBeenCalled();expect(c.errorMessage).toContain('choices are preserved');c.selectedFiles=[];c.sendMessage();expect(api.sendMessage.mock.calls[0][4]).toEqual(values);
 });
 it('retains Company selections and the question id when retrying',()=>{
  const first=new Subject<any>(),api={sendMessage:vi.fn().mockReturnValueOnce(first).mockReturnValue(new Subject())};const c=company(api);c.chooseAnswer(values,{id:'q'} as never);first.error(new HttpErrorResponse({status:422}));c.sendMessage();expect(api.sendMessage.mock.calls[1]).toEqual([values.join('; '),'q',values]);
 });
 it('does not attach old Company values to a new custom answer',()=>{
  const first=new Subject<any>(),api={sendMessage:vi.fn().mockReturnValueOnce(first).mockReturnValue(new Subject())};const c=company(api);c.chooseAnswer(values,{id:'q'} as never);first.error(new HttpErrorResponse({status:422}));c.writeCustomAnswer({id:'next'} as never);c.prompt='New answer';c.sendMessage();expect(api.sendMessage.mock.calls[1]).toEqual(['New answer','next']);
 });
 it('keeps ordinary single-choice actions on the legacy text contract',()=>{
  const api={sendMessage:vi.fn().mockReturnValue(new Subject())};const c=company(api);c.chooseAnswer('Provide later',{id:'q'} as never);expect(api.sendMessage).toHaveBeenCalledWith('Provide later','q');
 });
});
