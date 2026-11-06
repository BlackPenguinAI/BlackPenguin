import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { describe, it, expect, afterEach } from 'vitest';
import { StaffMonitorComponent } from './monitor';

describe('Staged monitor evidence', () => {
  afterEach(() => TestBed.resetTestingModule());
  it('renders escaped expandable diagnostics and clears them when scope changes', () => {
    TestBed.configureTestingModule({ imports:[StaffMonitorComponent], providers:[
      provideHttpClient(), provideHttpClientTesting(), provideRouter([])] });
    const fixture=TestBed.createComponent(StaffMonitorComponent);
    const component=fixture.componentInstance;
    const http=TestBed.inject(HttpTestingController);
    http.expectOne(r=>r.url.includes('/companies?')).flush({items:[],has_more:false});
    component.conversation='c';
    component.dialogueEvents=[{revision:3,kind:'state_update',payload_json:{draft:{text:'<img src=x onerror=alert(1)>'}}}];
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('details summary').textContent).toContain('Revision 3');
    expect(fixture.nativeElement.querySelector('pre').textContent).toContain('<img');
    expect(fixture.nativeElement.querySelector('pre img')).toBeNull();
    component.company='next';component.companyChanged();
    http.expectOne(r=>r.url.includes('/projects?')).flush([]);
    expect(component.dialogueEvents).toEqual([]);
    component.ngOnDestroy();http.verify();
  });
});
