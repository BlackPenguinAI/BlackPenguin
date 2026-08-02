import { inject } from '@angular/core';
import {
  HttpErrorResponse,
  HttpInterceptorFn,
} from '@angular/common/http';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { AuthService } from '../services/auth';

let unauthorizedRedirectInProgress = false;

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.getToken();
  const isApiRequest = request.url.includes('/api/v1/');
  const isPublicAuthRequest =
    request.url.includes('/auth/login') ||
    request.url.includes('/auth/register') ||
    request.url.includes('/auth/set-password');

  const outgoingRequest = token && isApiRequest && !isPublicAuthRequest
    ? request.clone({
        setHeaders: { Authorization: `Bearer ${token}` },
      })
    : request;

  return next(outgoingRequest).pipe(
    catchError((error: HttpErrorResponse) => {
      if (
        error.status === 401 &&
        isApiRequest &&
        !isPublicAuthRequest &&
        !unauthorizedRedirectInProgress
      ) {
        unauthorizedRedirectInProgress = true;
        auth.logout();

        void router.navigate(['/login'], {
          replaceUrl: true,
          queryParams: { sessionExpired: true },
        }).finally(() => {
          unauthorizedRedirectInProgress = false;
        });
      }

      return throwError(() => error);
    }),
  );
};
