import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { StaffMonitorComponent } from './monitor';
import { routes } from '../../app.routes';

describe('Staff monitor', () => {
  let http: HttpTestingController;
  let component: StaffMonitorComponent;
  let fixture: ComponentFixture<StaffMonitorComponent>;
  const root='http://localhost:8000/api/v1/monitor';
  beforeEach(() => {
    TestBed.configureTestingModule({imports:[StaffMonitorComponent],providers:[provideHttpClient(),provideHttpClientTesting(),provideRouter([])]});
    http=TestBed.inject(HttpTestingController);
    fixture=TestBed.createComponent(StaffMonitorComponent);
    component=fixture.componentInstance;
    http.expectOne(root+'/companies?offset=0').flush({items:[{id:'a',name:'Company A'}],has_more:false});
  });
  afterEach(() => { component.ngOnDestroy(); http.verify(); TestBed.resetTestingModule(); });
  it('is only routed for staff outside the admin and company menus', () => {
    const route=routes.find(r=>r.path==='monitor');
    expect(route?.data?.['roles']).toEqual(['superadmin']);
    expect(route?.canActivate?.length).toBe(2);
    expect(routes.find(r=>r.path==='admin')?.children?.some(r=>r.path==='monitor')).toBe(false);
  });
  it('clears dependent choices and ignores an old selection response', () => {
    component.company='a'; component.companyChanged();
    const old=http.expectOne(root+'/projects?company_id=a');
    component.company='b'; component.companyChanged();
    http.expectOne(root+'/projects?company_id=b').flush([{id:'b-project',name:'B'}]);
    old.flush([{id:'a-project',name:'A'}]);
    expect(component.projects[0].id).toBe('b-project');
    expect(component.lead).toBe(''); expect(component.messages).toEqual([]);
  });
  it('loads incremental messages without duplication and updates delivery and pause status', () => {
    component.company='a';component.project='p';component.lead='l';component.conversation='c';
    component.refresh();
    http.expectOne(r=>r.url.includes('/conversations/c?')).flush({messages:[{id:'1',direction:'outbound',status:'sent'}],next_cursor:'1',has_more:false,delivery_statuses:[],is_paused:false});
    component.refresh();
    http.expectOne(r=>r.url.includes('after=1')).flush({messages:[{id:'1'}],next_cursor:'1',has_more:false,delivery_statuses:[{message_id:'1',status:'delivered'}],is_paused:true,pause_reason:'Human review'});
    expect(component.messages.length).toBe(1); expect(component.messages[0].status).toBe('delivered');
    expect(component.paused).toBe(true);expect(component.pauseReason).toBe('Human review');
  });
  it('does not carry old messages or pause state into another opportunity', () => {
    component.messages=[{id:'old'}];component.paused=true;component.pauseReason='old';component.company='a';component.project='p';component.lead='new';
    component.leadChanged();
    http.expectOne(r=>r.url.includes('/conversations?')).flush([]);
    expect(component.messages).toEqual([]);expect(component.paused).toBe(false);expect(component.pauseReason).toBe('');
  });
  it('shows a readable error and allows retry after an HTTP failure', () => {
    component.conversation='c';component.refresh();
    http.expectOne(r=>r.url.includes('/conversations/c?')).flush({detail:'Staff session expired'},{status:403,statusText:'Forbidden'});
    expect(component.busy).toBe(false);expect(component.error).toBe('Staff session expired');
  });
  it('renders message contents as plain text and preserves line breaks', () => {
    component.conversation='c';
    component.messages=[{id:'m',content:'1. First\n\n2. Second <img src=x onerror=alert(1)>',created_at:'2026-11-04T12:00:00+00:00'}];
    fixture.detectChanges();
    const message=fixture.nativeElement.querySelector('article p');
    expect(message.textContent).toContain('1. First\n\n2. Second');
    expect(message.classList.contains('whitespace-pre-wrap')).toBe(true);
    expect(message.querySelector('img')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('UTC');
  });
  it('resets lead pagination when Company or Project changes', () => {
    component.leadsMore=true;component.company='a';component.companyChanged();
    http.expectOne(root+'/projects?company_id=a').flush([]);
    expect(component.leadsMore).toBe(false);
    component.leadsMore=true;component.project='p';component.projectChanged();
    http.expectOne(r=>r.url.includes('/leads?')).flush({items:[],has_more:false});
    expect(component.leadsMore).toBe(false);
  });
  it('ignores a stale export after selecting another opportunity', () => {
    component.company='a';component.project='p';component.lead='old';component.conversation='c';
    component.download();
    const previous=http.expectOne(r=>r.url.includes('/conversations/c/export?'));
    expect(previous.request.method).toBe('GET');
    expect(previous.request.responseType).toBe('blob');
    component.lead='new';component.leadChanged();
    http.expectOne(r=>r.url.includes('/conversations?')).flush([]);
    expect(component.exporting).toBe(false);
    previous.flush(new Blob(['old opportunity data']));
    expect(component.messages).toEqual([]);expect(component.error).toBe('');
  });
});
