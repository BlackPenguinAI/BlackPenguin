import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { EmailSettingsPageComponent } from './email-settings-page';

describe('EmailSettingsPageComponent', () => {
  it('saves Firebase REST fields without requesting a service-account JSON', () => {
    vi.stubGlobal('localStorage', { getItem: vi.fn().mockReturnValue('test-token') });
    const http = {
      put: vi.fn().mockReturnValue(of({ is_enabled: false, verification_status: 'pending' })),
    };
    const component = new EmailSettingsPageComponent(
      http as any, { showSuccess: vi.fn(), showError: vi.fn() } as any,
      { detectChanges: vi.fn() } as any,
    );
    component.firebaseConfig.project_id = 'blackpenguinai';
    component.firebaseConfig.api_key = 'public-web-api-key';
    component.saveConfig();
    const payload = http.put.mock.calls[0][1];
    expect(payload.auth_mode).toBe('rest');
    expect(payload.project_id).toBe('blackpenguinai');
    expect(payload.credentials_json).toBeUndefined();
  });
});
