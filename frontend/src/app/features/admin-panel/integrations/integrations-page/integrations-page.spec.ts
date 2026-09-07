import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { IntegrationsPageComponent } from './integrations-page';

describe('IntegrationsPageComponent', () => {
  it('starts with the production callback and disabled integration', () => {
    const component = new IntegrationsPageComponent({} as any, {} as any, {} as any);
    expect(component.config.redirect_uri).toContain('/sales/calendar/google/callback');
    expect(component.config.is_enabled).toBe(false);
    expect(component.metaConfig.graph_api_version).toBe('v26.0');
    expect(component.metaPublicUrls.dataDeletion).toBe('https://blackpenguin.ai/legal/data-deletion');
    expect(component.metaDemoReady).toBe(false);
  });

  it('marks the demo preflight ready only after credentials, webhook and enablement', () => {
    const component = new IntegrationsPageComponent({} as any, {} as any, {} as any);
    Object.assign(component.metaConfig, {
      app_id: '123', app_secret_configured: true, login_config_id: '456',
      webhook_verify_token_configured: true, verification_status: 'verified', is_enabled: true,
    });
    expect(component.metaDemoReady).toBe(true);
  });
});
