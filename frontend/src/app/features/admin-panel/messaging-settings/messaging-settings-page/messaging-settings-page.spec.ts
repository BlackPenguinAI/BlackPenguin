import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { MessagingSettingsPageComponent } from './messaging-settings-page';

describe('MessagingSettingsPageComponent', () => {
  it('does not test credentials while unsaved values are present', () => {
    let error = '';
    const component = new MessagingSettingsPageComponent({ post: () => { throw new Error('must not call'); } } as any, { showError: (value: string) => error = value } as any, {} as any);
    component.isDirty = true;
    component.verifyConfig();
    expect(error).toContain('Save');
  });
});
