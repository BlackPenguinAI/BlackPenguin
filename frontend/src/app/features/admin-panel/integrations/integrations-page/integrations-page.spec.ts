import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { IntegrationsPageComponent } from './integrations-page';

describe('IntegrationsPageComponent', () => {
  it('starts with the production callback and disabled integration', () => {
    const component = new IntegrationsPageComponent({} as any, {} as any, {} as any);
    expect(component.config.redirect_uri).toContain('/sales/calendar/google/callback');
    expect(component.config.is_enabled).toBe(false);
  });
});
