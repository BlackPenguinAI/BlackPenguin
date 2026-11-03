import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { firstValueFrom, Observable, of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { CompanyOnboardingService } from '../../pages/chat/company-onboarding.service';
import { companyCompletionGuard } from './company-completion.guard';

describe('Company completion guard and published revisions', () => {
  async function allowed(completion: Record<string, unknown>) {
    const redirect = { redirect: '/app/company/onboarding' };
    TestBed.configureTestingModule({ providers: [
      { provide: CompanyOnboardingService, useValue: { getProfile: () => of({ completion }) } },
      { provide: Router, useValue: { createUrlTree: vi.fn(() => redirect) } },
    ] });
    const value = TestBed.runInInjectionContext(() => companyCompletionGuard({} as never, {} as never));
    return firstValueFrom(value as Observable<unknown>);
  }
  it('keeps an approved Company accessible while its next draft is pending', async () => {
    expect(await allowed({ can_complete: false, final_approved: false, active_profile_approved: true, has_pending_changes: true })).toBe(true);
  });
  it('does not treat a deferred or 100 percent unapproved profile as active', async () => {
    expect(await allowed({ percentage: 100, can_complete: false, final_approved: false })).toEqual({ redirect: '/app/company/onboarding' });
  });
  it('preserves the legacy approved-profile route', async () => {
    expect(await allowed({ can_complete: true, final_approved: true })).toBe(true);
  });
});
