import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

export interface OnboardingQuestion {
  field: string | null;
  label: string;
  prompt: string;
  input_type: string;
  options: string[];
  examples: string[];
  allow_custom: boolean;
  minimum_words: number | null;
}

@Component({
  selector: 'app-onboarding-response-options',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './onboarding-response-options.html',
  styleUrl: './onboarding-response-options.scss',
})
export class OnboardingResponseOptionsComponent {
  @Input({ required: true }) question!: OnboardingQuestion;
  @Input() disabled = false;
  @Input() selectedChoice: string | null = null;
  @Input() answered = false;
  @Input() showPrompt = true;
  @Output() selected = new EventEmitter<string>();
  @Output() custom = new EventEmitter<void>();

  get choices(): string[] {
    return this.question.options.length ? this.question.options : this.question.examples;
  }
}
