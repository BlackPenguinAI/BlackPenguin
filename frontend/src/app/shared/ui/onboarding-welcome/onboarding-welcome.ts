import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

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

  get valid(): boolean { try { const value = new URL(this.url.trim()); return ['http:', 'https:'].includes(value.protocol); } catch { return false; } }
  submit(): void { this.touched = true; if (this.valid && !this.busy) this.continueWithUrl.emit(this.url.trim()); }
}
