import '@angular/compiler';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { afterEach, expect, it, vi } from 'vitest';
import { of, Subject, throwError } from 'rxjs';
import { OnboardingLocationComponent } from '../../../../shared/ui/onboarding-location';
import { ProjectChatComponent } from './project-chat';
import { EMPTY_PROJECT_PROFILE } from './project-onboarding.models';
import { ChatComponent } from '../../../chat/chat';
import { EMPTY_COMPANY_PROFILE } from '../../../chat/company-onboarding.models';

afterEach(()=>{vi.restoreAllMocks();TestBed.resetTestingModule();});
const cities=[{country:'US',city:'Miami',timezone:'America/New_York'},{country:'US',city:'Chicago',timezone:'America/Chicago'},{country:'PE',city:'Lima',timezone:'America/Lima'}];
const options={countries:[{code:'US',name:'United States'},{code:'PE',name:'Peru'}],cities,country:'US',city:'Miami',timezone:'America/New_York',source:'Project website'};
it('renders selectable country, city suggestions and timezone without submitting automatically',async()=>{
 TestBed.configureTestingModule({imports:[OnboardingLocationComponent],providers:[provideHttpClient(),provideHttpClientTesting()]});
 const f=TestBed.createComponent(OnboardingLocationComponent);f.componentInstance.entityId='project-1';
 const http=TestBed.inject(HttpTestingController);f.detectChanges();
 http.expectOne(r=>r.url.endsWith('/project/project-1/location')).flush(options);f.detectChanges();await f.whenStable();
 expect(f.nativeElement.querySelectorAll('select').length).toBe(1);
 expect(f.nativeElement.querySelector('app-timezone-select')).toBeTruthy();
 expect(f.nativeElement.querySelectorAll('datalist option').length).toBe(2);
 expect(f.nativeElement.textContent).toContain('Project website');
 http.expectNone(r=>r.method==='POST');f.destroy();http.verify();
});
it('clears incompatible city and timezone when country changes',()=>{
 const c=new OnboardingLocationComponent({} as any,{markForCheck:vi.fn()} as any);c.options=options;c.country='PE';c.city='Miami';c.timezone='America/New_York';
 c.countryChanged();expect(c.city).toBe('');expect(c.timezone).toBe('');expect(c.zones).toEqual(['America/Lima']);
});
it('suggests by country and city, but unknown city requires an explicit timezone selection',()=>{
 const c=new OnboardingLocationComponent({} as any,{markForCheck:vi.fn()} as any);c.options=options;c.country='US';c.city='Chicago';
 c.cityChanged();expect(c.timezone).toBe('America/Chicago');
 c.city='Another city';c.cityChanged();expect(c.timezone).toBe('');expect(c.zones).toHaveLength(2);
});
it('keeps selections on failed save and renders a readable error',()=>{
 const post=vi.fn(()=>throwError(()=>({error:{detail:'Choose a matching timezone.'}})));
 const c=new OnboardingLocationComponent({post} as any,{markForCheck:vi.fn()} as any);
 c.options=options;c.entityId='project-1';c.country='US';c.city='Another city';c.timezone='America/Chicago';c.save();
 expect(c.city).toBe('Another city');expect(c.timezone).toBe('America/Chicago');expect(c.message).toContain('matching timezone');expect(c.busy).toBe(false);
});
function project(api:any){
 const c=new ProjectChatComponent({} as any,api,{detectChanges:vi.fn(),markForCheck:vi.fn()} as any,{isSupported:false} as any,{} as any);
 c.projectId='project-1';return c;
}
const question={task:'meta_account',input_type:'meta_lead_setup',field:'campaigns_defined',label:'Meta',prompt:'Meta',options:[],examples:[],allow_custom:false,minimum_words:null};
const turn:any={message:{id:'new-answer',sender:'ai',content:'I understood: Meta account',created_at:'2026-11-04T22:00:00Z',ui_payload:question,attachments:[]},user_message:null,profile:EMPTY_PROJECT_PROFILE,next_question:question,sources:[]};
it('does not let an older state request erase an immediately rendered editor reply',()=>{
 const stale=new Subject<any>();const c=project({getState:()=>stale});c.prompt='Keep this draft';
 (c as any).syncState();(c as any).applyTurn(turn);
 stale.next({version:999,profile:EMPTY_PROJECT_PROFILE,messages:[],sources:[],next_question:null,stage:'complete'});
 expect(c.messages.map(m=>m.id)).toEqual(['new-answer']);expect(c.prompt).toBe('Keep this draft');expect(c.nextQuestion?.task).toBe('meta_account');
});
it('deduplicates repeated turn delivery without losing reply order',()=>{
 const c=project({});(c as any).applyTurn(turn);(c as any).applyTurn(turn);
 expect(c.messages).toHaveLength(1);
});
it('opens the same persisted task through the explicit editor endpoint without navigating',()=>{
 const api={openEditorTask:vi.fn(()=>of(turn))};const c=project(api);vi.spyOn(c as any,'scrollToBottom').mockImplementation(()=>undefined);
 c.openEditorTask('meta_account');expect(api.openEditorTask).toHaveBeenCalledWith('project-1','meta_account',expect.any(String),expect.objectContaining({expected_navigation_revision:0}));
 expect(c.isAnalyzing).toBe(false);expect(c.nextQuestion?.task).toBe('meta_account');
});

it.each([0,401,500,502,504])('ignores stale Project state errors (%s) after the successful editor turn',(status)=>{
 const stale=new Subject<any>();const c=project({getState:()=>stale});c.initialState='ready';c.prompt='Keep my draft';
 (c as any).syncState();(c as any).applyTurn(turn);stale.error({status});
 expect(c.messages.map(m=>m.id)).toEqual(['new-answer']);expect(c.nextQuestion?.task).toBe('meta_account');
 expect(c.initialState).toBe('ready');expect(c.errorMessage).toBe('');expect(c.prompt).toBe('Keep my draft');
});
it('still shows a current Project synchronization failure',()=>{
 const request=new Subject<any>();const c=project({getState:()=>request});c.initialState='ready';
 (c as any).syncState();request.error({status:500});
 expect(c.initialState).toBe('error');expect(c.errorMessage).toContain('could not be synchronized');
});
it.each([0,401,500,502,504])('ignores stale Company state errors (%s) after a successful turn',(status)=>{
 const old=new Subject<any>(),current=new Subject<any>();let calls=0;
 const c=new ChatComponent({use:vi.fn()} as any,{getState:()=>++calls===1?old:current} as any,{detectChanges:vi.fn(),markForCheck:vi.fn()} as any,{isSupported:false} as any,{} as any);
 c.initialState='ready';c.prompt='Keep Company draft';(c as any).syncState();
 (c as any).applyTurn({...turn,profile:EMPTY_COMPANY_PROFILE});old.error({status});
 expect(c.messages.map(m=>m.id)).toEqual(['new-answer']);expect(c.initialState).toBe('ready');
 expect(c.errorMessage).toBe('');expect(c.prompt).toBe('Keep Company draft');
});
it('still shows a current Company synchronization failure',()=>{
 const request=new Subject<any>();const c=new ChatComponent({use:vi.fn()} as any,{getState:()=>request} as any,{detectChanges:vi.fn(),markForCheck:vi.fn()} as any,{isSupported:false} as any,{} as any);
 c.initialState='ready';(c as any).syncState();request.error({status:500});
 expect(c.initialState).toBe('error');expect(c.errorMessage).toContain('could not be synchronized');
});

