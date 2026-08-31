import '@angular/compiler';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { ActivateAccountComponent } from './activate-account';

describe('ActivateAccountComponent', () => {
  function component(code = 'valid-code') {
    const route = { snapshot: { queryParamMap: { get: () => code } } } as any;
    const router = { navigateByUrl: vi.fn() } as any;
    const auth = {
      inspectActivation: vi.fn().mockReturnValue(of({
        email: 'sales@example.com', first_name: 'Sam', role: 'sales', company_name: 'Northstar', flow: 'invitation',
      })),
      completeActivation: vi.fn().mockReturnValue(of({ role: 'sales', access_token: 'token' })),
      defaultRouteForRole: vi.fn().mockReturnValue('/app/dashboard'),
    } as any;
    return { value: new ActivateAccountComponent(route, router, auth), router, auth };
  }

  it('validates the Firebase action code before showing the password form', () => {
    const { value, auth } = component();
    value.ngOnInit();
    expect(auth.inspectActivation).toHaveBeenCalledWith('valid-code');
    expect(value.invitation.email).toBe('sales@example.com');
  });

  it('requires a strong matching password and activates the account', () => {
    const { value, auth, router } = component();
    value.ngOnInit();
    value.password = 'Secure#Pass1';
    value.confirmPassword = 'Secure#Pass1';
    expect(value.valid).toBe(true);
    value.activate();
    expect(auth.completeActivation).toHaveBeenCalledWith('valid-code', 'Secure#Pass1');
    expect(router.navigateByUrl).toHaveBeenCalledWith('/app/dashboard', { replaceUrl: true });
  });

  it('shows an invalid-link state without requesting a password', () => {
    const { value, auth } = component();
    auth.inspectActivation.mockReturnValue(throwError(() => new Error('Expired')));
    value.ngOnInit();
    expect(value.invitation).toBeNull();
    expect(value.error).toBe('Expired');
  });
});
