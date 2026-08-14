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
  minimum_characters?: number | null;
  help_text?: string | null;
  answer_actions?: Record<string, { kind: string; source_field?: string }>;
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
    const options = Array.isArray(this.question?.options) ? this.question.options : [];
    const examples = Array.isArray(this.question?.examples) ? this.question.examples : [];
    return options.length ? options : examples;
  }

  get isStructuredStep(): boolean {
    return ['project_sales_team', 'meta_lead_setup'].includes(this.question?.input_type || '');
  }
}
