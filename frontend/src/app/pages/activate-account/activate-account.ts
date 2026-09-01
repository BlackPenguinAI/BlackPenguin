import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';

import { AuthService } from '../../core/services/auth';

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
  invitation: any = null;
  password = '';
  confirmPassword = '';
  showPassword = false;
  private code = '';
  private state = '';

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly auth: AuthService,
  ) {}

  ngOnInit(): void {
    this.code = this.route.snapshot.queryParamMap.get('oobCode') || '';
    this.state = this.route.snapshot.queryParamMap.get('state') || '';
    const continueUrl = this.route.snapshot.queryParamMap.get('continueUrl');
    if (continueUrl) {
      try {
        const nested = new URL(continueUrl);
        this.state ||= nested.searchParams.get('state') || '';
        this.code ||= nested.searchParams.get('oobCode') || '';
      } catch {
        // Firebase may omit continueUrl after redirecting; direct parameters remain authoritative.
      }
    }
    if (!this.code || !this.state) {
      this.loading = false;
      this.error = 'This activation link is incomplete.';
      return;
    }
    this.auth.inspectActivation(this.state).subscribe({
      next: value => { this.invitation = value; this.loading = false; },
      error: err => { this.error = err.message || 'This activation link is invalid or expired.'; this.loading = false; },
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
    this.saving = true; this.error = '';
    this.auth.completeActivation(this.state, this.code, this.password).subscribe({
      next: response => {
        void this.router.navigateByUrl(this.auth.defaultRouteForRole(response.role), { replaceUrl: true });
      },
      error: err => { this.error = err.message || 'Account activation failed.'; this.saving = false; },
    });
  }
}
