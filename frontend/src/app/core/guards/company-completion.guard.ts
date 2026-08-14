import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { CompanyOnboardingService } from '../../pages/chat/company-onboarding.service';

/** Keep partial Admin data out of Company Overview until onboarding is approved. */
export const companyCompletionGuard: CanActivateFn = () => {
  const onboarding = inject(CompanyOnboardingService);
  const router = inject(Router);
  const onboardingUrl = router.createUrlTree(['/app/company/onboarding']);

  return onboarding.getProfile().pipe(
    map(profile => profile.completion.can_complete && profile.completion.final_approved
      ? true
      : onboardingUrl),
    catchError(() => of(onboardingUrl)),
  );
};
