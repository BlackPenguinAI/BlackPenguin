import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { MessagingSettingsPageComponent } from './messaging-settings-page';

describe('MessagingSettingsPageComponent', () => {
  it('does not test credentials while unsaved values are present', () => {
    let error = '';
    const component = new MessagingSettingsPageComponent({ post: () => { throw new Error('must not call'); } } as any, { showError: (value: string) => error = value } as any, {} as any);
    component.dirty.twilio = true;
    component.verify('twilio');
    expect(error).toContain('Save');
  });

  it('does not allow an unverified provider to become the default', () => {
    const component = new MessagingSettingsPageComponent({ put: () => { throw new Error('must not call'); } } as any, {} as any, {} as any);
    component.defaultProvider = 'twilio';
    component.telnyx.verification_status = 'pending';
    component.telnyx.live_sms_enabled = false;
    expect(component.defaultProvider).toBe('twilio');
  });
});
