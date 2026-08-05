import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';

import { ChatComponent } from './chat';
import { EMPTY_COMPANY_PROFILE } from './company-onboarding.models';


describe('ChatComponent', () => {
  let component: ChatComponent;
  let fixture: ComponentFixture<ChatComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChatComponent, HttpClientTestingModule, TranslateModule.forRoot()],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatComponent);
    component = fixture.componentInstance;
  });

  afterEach(() => localStorage.clear());

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should not render the chat before the initial state is loaded', () => {
    expect(component.initialState).toBe('loading');
    expect(component.showWelcome).toBe(false);
  });

  it('should expose required and conditional fields separately', () => {
    component.profile = {
      ...EMPTY_COMPANY_PROFILE,
      fields: [
        {
          key: 'official_company_name',
          label: 'Official company name',
          requirement: 'required',
          status: 'confirmed',
          applicable: null,
        },
        {
          key: 'dba',
          label: 'DBA',
          requirement: 'conditionally_required',
          status: 'not_applicable',
          applicable: false,
        },
      ],
    };

    expect(component.requiredFields.map((field) => field.key)).toEqual(['official_company_name']);
    expect(component.conditionalFields.map((field) => field.key)).toEqual(['dba']);
  });

  it('should use distinct icons for confirmed, pending and conflicting fields', () => {
    expect(component.statusIcon('confirmed')).toBe('check_circle');
    expect(component.statusIcon('pending_confirmation')).toBe('schedule');
    expect(component.statusIcon('conflicting')).toBe('error');
  });

  it('should expose onboarding status labels in English', () => {
    expect(component.statusLabel('missing')).toBe('Missing');
    expect(component.statusLabel('pending_confirmation')).toBe('Pending confirmation');
    expect(component.statusLabel('not_applicable')).toBe('Not applicable');
  });

  it('should not expose the removed session initializer', () => {
    expect((component as unknown as { initSession?: unknown }).initSession).toBeUndefined();
  });

  it('should render assistant markdown instead of exposing formatting tokens', () => {
    const html = component.renderMarkdown('Updated **Official company name**.');
    expect(html).toContain('<strong>Official company name</strong>');
    expect(html).not.toContain('**Official');
  });

  it('should format structured source values for editing', () => {
    expect(component.formatValue({ exists: false, url: null })).toBe('{"exists":false,"url":null}');
  });
});
