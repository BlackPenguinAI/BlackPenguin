import { ChangeDetectorRef } from '@angular/core';

import { SpeechSynthesisService } from '../../../core/services/speech-synthesis.service';
import { OnboardingAiMessageComponent } from './onboarding-ai-message';


describe('OnboardingAiMessageComponent', () => {
  it('does not read missing choices from a historical terminal payload', () => {
    const component = new OnboardingAiMessageComponent(
      {} as SpeechSynthesisService,
      {} as ChangeDetectorRef,
    );
    component.message = {
      id: 'failure-1',
      content: 'The source failed.',
      created_at: new Date(),
      ui_payload: { kind: 'source_processing_failed' } as never,
    };

    expect(component.choicesText).toBe('');
  });
});
