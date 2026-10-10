import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

export function normalizeOnboardingUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  if (/^www\./i.test(trimmed)) return `https://${trimmed}`;
  if (!/^[a-z][a-z\d+.-]*:\/\//i.test(trimmed) && /^[\w-]+(?:\.[\w-]+)+(?:[/:?#].*)?$/i.test(trimmed)) {
    return `https://${trimmed}`;
  }
  return trimmed;
}

@Component({
  selector: 'app-onboarding-welcome', standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './onboarding-welcome.html', styleUrl: './onboarding-welcome.scss',
})
export class OnboardingWelcomeComponent {
  @Input() kind: 'company' | 'project' = 'company';
  @Input() firstName = '';
  @Input() busy = false;
  @Output() continueWithUrl = new EventEmitter<string>();
  @Output() skip = new EventEmitter<void>();
  url = '';
  touched = false;

  get normalizedUrl(): string { return normalizeOnboardingUrl(this.url); }
  get valid(): boolean { try { const value = new URL(this.normalizedUrl); return ['http:', 'https:'].includes(value.protocol) && !!value.hostname; } catch { return false; } }
  normalizeUrlInput(): void { if (this.valid) this.url = this.normalizedUrl; }
  submit(): void {
    this.touched = true;
    if (!this.valid || this.busy) return;
    this.url = this.normalizedUrl;
    this.continueWithUrl.emit(this.url);
  }
}
