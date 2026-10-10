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
  suggestion_origin?: 'website' | 'confirmed_context' | 'generic_fallback' | null;
  suggestion_sources?: string[];
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
  readonly selectedValues = new Set<string>();

  get choices(): string[] {
    const options = Array.isArray(this.question?.options) ? this.question.options : [];
    const examples = Array.isArray(this.question?.examples) ? this.question.examples : [];
    return options.length ? options : examples;
  }

  get isStructuredStep(): boolean {
    return ['ai_sales_authorization', 'project_sales_team', 'meta_lead_setup'].includes(this.question?.input_type || '');
  }

  get isMultiSelect(): boolean {
    return this.question?.input_type === 'multi_select' && Array.isArray(this.question?.options) && this.question.options.length > 0;
  }

  choose(choice: string): void {
    if (!this.isMultiSelect) {
      this.selected.emit(choice);
      return;
    }
    if (this.selectedValues.has(choice)) this.selectedValues.delete(choice);
    else this.selectedValues.add(choice);
  }

  isSelected(choice: string): boolean {
    return this.isMultiSelect ? this.selectedValues.has(choice) : choice === this.selectedChoice;
  }

  submitSelection(): void {
    if (!this.selectedValues.size || this.disabled) return;
    this.selected.emit([...this.selectedValues].join('; '));
  }

  get suggestionLabel(): string {
    if (this.question.suggestion_origin === 'website') return 'Based on your website and confirmed information';
    if (this.question.suggestion_origin === 'confirmed_context') return 'Based on your confirmed answers';
    if (this.question.suggestion_origin === 'generic_fallback') return 'Starter suggestions';
    return '';
  }
}
