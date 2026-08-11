import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from '../services/auth';


export const roleGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const allowed = (route.data?.['roles'] as string[] | undefined) ?? [];
  const role = auth.getRole();
  if (role && (allowed.length === 0 || allowed.includes(role))) return true;
  return router.createUrlTree([auth.defaultRouteForRole(role)]);
};
