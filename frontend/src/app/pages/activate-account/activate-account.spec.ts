import '@angular/compiler';
import { of, Subject, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { ActivateAccountComponent } from './activate-account';

describe('ActivateAccountComponent', () => {
  function component(code = 'valid-code', state = 'signed-invitation-state') {
    const params: Record<string, string | null> = { oobCode: code, state, continueUrl: null };
    const route = {
      snapshot: {
        queryParamMap: {
          get: (key: string) => params[key] ?? null,
        },
      },
    } as any;
    const router = { navigateByUrl: vi.fn() } as any;
    const cdr = { detectChanges: vi.fn() } as any;
    const auth = {
      inspectActivation: vi.fn().mockReturnValue(of({
        email: 'sales@example.com', first_name: 'Sam', role: 'sales', company_name: 'Northstar', flow: 'invitation',
      })),
      completeActivation: vi.fn().mockReturnValue(of({ role: 'sales', access_token: 'token' })),
      defaultRouteForRole: vi.fn().mockReturnValue('/app/dashboard'),
    } as any;
    return { value: new ActivateAccountComponent(route, router, auth, cdr), router, auth, cdr };
  }

  it('validates the Firebase action code before showing the password form', () => {
    const { value, auth, cdr } = component();
    value.ngOnInit();
    expect(auth.inspectActivation).toHaveBeenCalledWith('signed-invitation-state');
    expect(value.invitation.email).toBe('sales@example.com');
    expect(cdr.detectChanges).toHaveBeenCalled();
  });

  it('requires a strong matching password and activates the account', () => {
    const { value, auth, router } = component();
    value.ngOnInit();
    value.password = 'Secure#Pass1';
    value.confirmPassword = 'Secure#Pass1';
    expect(value.valid).toBe(true);
    value.activate();
    expect(auth.completeActivation).toHaveBeenCalledWith(
      'signed-invitation-state', 'valid-code', 'Secure#Pass1',
    );
    expect(router.navigateByUrl).toHaveBeenCalledWith('/app/dashboard', { replaceUrl: true });
  });

  it('shows an invalid-link state without requesting a password', () => {
    const { value, auth, cdr } = component();
    auth.inspectActivation.mockReturnValue(throwError(() => new Error('Expired')));
    value.ngOnInit();
    expect(value.invitation).toBeNull();
    expect(value.error).toBe('Expired');
    expect(cdr.detectChanges).toHaveBeenCalled();
  });

  it('rejects links that do not carry both Firebase code and signed state', () => {
    const { value, auth } = component('', 'signed-invitation-state');
    value.ngOnInit();
    expect(auth.inspectActivation).not.toHaveBeenCalled();
    expect(value.error).toBe('This activation link is incomplete.');
  });

  it('stops validating and shows an actionable message when the backend does not respond', () => {
    vi.useFakeTimers();
    try {
      const { value, auth, cdr } = component();
      auth.inspectActivation.mockReturnValue(new Subject());
      value.ngOnInit();
      expect(value.loading).toBe(true);

      vi.advanceTimersByTime(15_001);

      expect(value.loading).toBe(false);
      expect(value.error).toContain('could not validate the invitation in time');
      expect(cdr.detectChanges).toHaveBeenCalled();

      auth.inspectActivation.mockReturnValue(of({
        email: 'sales@example.com', first_name: 'Sam', role: 'sales', company_name: 'Northstar', flow: 'invitation',
      }));
      value.retryValidation();
      expect(auth.inspectActivation).toHaveBeenCalledTimes(2);
      expect(value.loading).toBe(false);
      expect(value.invitation.email).toBe('sales@example.com');
    } finally {
      vi.useRealTimers();
    }
  });

  it('restores the activation form when Firebase completion fails', () => {
    const { value, auth, cdr } = component();
    value.ngOnInit();
    value.password = 'Secure#Pass1';
    value.confirmPassword = 'Secure#Pass1';
    auth.completeActivation.mockReturnValue(throwError(() => new Error('Firebase rejected the link')));

    value.activate();

    expect(value.saving).toBe(false);
    expect(value.error).toBe('Firebase rejected the link');
    expect(cdr.detectChanges).toHaveBeenCalled();
  });
});
