import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { OnboardingResponseOptionsComponent } from './onboarding-response-options';


describe('OnboardingResponseOptionsComponent', () => {
  it('treats missing options and examples from historical payloads as empty', () => {
    const component = new OnboardingResponseOptionsComponent();
    component.question = { kind: 'source_processing_failed' } as never;

    expect(component.choices).toEqual([]);
  });

  it('prefers options and falls back to examples', () => {
    const component = new OnboardingResponseOptionsComponent();
    component.question = {
      field: null, label: 'Question', prompt: 'Choose', input_type: 'choice',
      options: ['A'], examples: ['B'], allow_custom: true, minimum_words: null,
    };
    expect(component.choices).toEqual(['A']);

    component.question = { ...component.question, options: [] };
    expect(component.choices).toEqual(['B']);
  });

  it('keeps explanatory help and typed answer actions in the question contract', () => {
    const component = new OnboardingResponseOptionsComponent();
    component.question = {
      field: 'dba', label: 'DBA (Doing Business As)', prompt: 'Does the company use a DBA?',
      input_type: 'conditional_text', options: ['No DBA — not applicable'], examples: [],
      allow_custom: true, minimum_words: null,
      help_text: 'A DBA (Doing Business As) is a registered trade or business name.',
      answer_actions: { 'No DBA — not applicable': { kind: 'not_applicable' } },
    };

    expect(component.question.help_text).toContain('Doing Business As');
    expect(component.question.answer_actions?.['No DBA — not applicable'].kind).toBe('not_applicable');
  });

  it('delegates structured Project steps to their dedicated cards', () => {
    const component = new OnboardingResponseOptionsComponent();
    component.question = {
      field: 'sales_contacts', label: 'Sales team', prompt: 'Assign Sales',
      input_type: 'project_sales_team', options: ['Configure later'], examples: [],
      allow_custom: true, minimum_words: null,
    };

    expect(component.isStructuredStep).toBe(true);
  });

  it('delegates explicit AI authorization to its consent card', () => {
    const component = new OnboardingResponseOptionsComponent();
    component.question = {
      field: 'sales_authorization', label: 'AI-assisted sales authorization', prompt: 'Authorize',
      input_type: 'ai_sales_authorization', options: [], examples: [],
      allow_custom: false, minimum_words: null,
    };

    expect(component.isStructuredStep).toBe(true);
  });

  it('labels grounded and fallback suggestions without presenting them as confirmed facts', () => {
    const component = new OnboardingResponseOptionsComponent();
    component.question = {
      field: 'corporate_differentiators', label: 'Differentiators', prompt: 'Choose',
      input_type: 'long_text', options: [], examples: ['Multifamily focus'],
      allow_custom: true, minimum_words: null, suggestion_origin: 'website',
      suggestion_sources: ['https://example.com'],
    };
    expect(component.suggestionLabel).toBe('Based on your website and confirmed information');

    component.question = { ...component.question, suggestion_origin: 'generic_fallback' };
    expect(component.suggestionLabel).toBe('Starter suggestions');
  });
});
