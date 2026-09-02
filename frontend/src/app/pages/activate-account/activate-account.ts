import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { timeout } from 'rxjs';

import { AuthService } from '../../core/services/auth';
import { activationLinkParameters } from './activation-link';

@Component({
  selector: 'app-activate-account',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './activate-account.html',
  styleUrl: './activate-account.scss',
})
export class ActivateAccountComponent implements OnInit {
  loading = true;
  saving = false;
  error = '';
  errorCode = '';
  invitation: any = null;
  password = '';
  confirmPassword = '';
  showPassword = false;
  private code = '';
  private state = '';
  private readonly validationTimeoutMs = 15_000;
  private readonly activationTimeoutMs = 20_000;

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly auth: AuthService,
    private readonly cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    const parameters = activationLinkParameters(
      key => this.route.snapshot.queryParamMap.get(key),
      this.route.snapshot.fragment || '',
    );
    this.code = parameters.oobCode;
    this.state = parameters.state;
    if (!this.code || !this.state) {
      this.loading = false;
      this.errorCode = 'INCOMPLETE_ACTIVATION_LINK';
      this.error = 'This activation link is incomplete.';
      return;
    }
    this.validateInvitation();
  }

  retryValidation(): void {
    if (!this.code || !this.state) return;
    this.loading = true;
    this.error = '';
    this.errorCode = '';
    this.invitation = null;
    this.cdr.detectChanges();
    this.validateInvitation();
  }

  private validateInvitation(): void {
    this.auth.inspectActivation(this.state).pipe(
      timeout({ first: this.validationTimeoutMs }),
    ).subscribe({
      next: value => {
        this.invitation = value;
        this.loading = false;
        this.cdr.detectChanges();
      },
      error: err => {
        this.errorCode = err?.code || '';
        this.error = err?.name === 'TimeoutError'
          ? 'Black Penguin could not validate the invitation in time. Please try again.'
          : (err.message || 'This activation link is invalid or expired.');
        this.loading = false;
        this.cdr.detectChanges();
      },
    });
  }

  get passwordChecks() {
    return {
      length: this.password.length >= 10,
      uppercase: /[A-Z]/.test(this.password),
      lowercase: /[a-z]/.test(this.password),
      number: /\d/.test(this.password),
      symbol: /[^A-Za-z0-9]/.test(this.password),
    };
  }

  get valid(): boolean {
    return Object.values(this.passwordChecks).every(Boolean) &&
      this.password === this.confirmPassword && !this.saving;
  }

  activate(): void {
    if (!this.valid) return;
    this.saving = true; this.error = ''; this.errorCode = '';
    this.auth.completeActivation(this.state, this.code, this.password).pipe(
      timeout({ first: this.activationTimeoutMs }),
    ).subscribe({
      next: response => {
        void this.router.navigateByUrl(this.auth.defaultRouteForRole(response.role), { replaceUrl: true });
      },
      error: err => {
        this.errorCode = err?.code || '';
        this.error = err?.name === 'TimeoutError'
          ? 'Firebase did not complete the activation in time. Your link is still safe; please try again.'
          : (err.message || 'Account activation failed.');
        this.saving = false;
        this.cdr.detectChanges();
      },
    });
  }
}
