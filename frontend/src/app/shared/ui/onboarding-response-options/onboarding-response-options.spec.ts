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
});
