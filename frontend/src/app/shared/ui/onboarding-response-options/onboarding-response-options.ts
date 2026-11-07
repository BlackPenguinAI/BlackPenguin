import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output, OnChanges } from '@angular/core';

export interface OnboardingQuestion {
  task?: string | null;
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
  exclusive_options?:string[];
  selected_values?:string[];
  detail_options?:string[];
}

@Component({
  selector: 'app-onboarding-response-options',
  standalone: true,
  imports: [CommonModule,FormsModule],
  templateUrl: './onboarding-response-options.html',
  styleUrl: './onboarding-response-options.scss',
})
export class OnboardingResponseOptionsComponent implements OnChanges {
  @Input({ required: true }) question!: OnboardingQuestion;
  @Input() disabled = false;
  @Input() selectedChoice: string | null = null;
  @Input() answered = false;
  @Input() showPrompt = true;
  @Output() selected = new EventEmitter<string | string[]>();
  @Output() deferred = new EventEmitter<string[]>();
  @Output() custom = new EventEmitter<void>();
  readonly selectedValues = new Set<string>();
  private selectionKey='';
  readonly optionDetails:Record<string,string>={};
  ngOnChanges():void {this.prepareSelection();}
  private prepareSelection():void {
    const key=JSON.stringify([this.question?.field,this.question?.input_type,this.question?.options,this.question?.selected_values,this.question?.detail_options]);
    if(key===this.selectionKey)return;
    this.selectionKey=key;this.selectedValues.clear();
    if(this.isMultiSelect)for(const value of this.question.selected_values || []) {
      if(typeof value==='string' && !this.isAction(value)) {
        const label=this.baseChoice(value);this.selectedValues.add(label);
        if(label!==value)this.optionDetails[label]=value.slice(label.length+1).trim();
      }
    }
  }
  isAction(choice:string):boolean {return ['not_applicable','defer'].includes(this.question?.answer_actions?.[choice]?.kind || '');}

  get choices(): string[] {
    const options = Array.isArray(this.question?.options) ? this.question.options : [];
    const examples = Array.isArray(this.question?.examples) ? this.question.examples : [];
    return [...new Set([...(options.length ? options : examples),...(this.isMultiSelect ? (this.question.selected_values || []).map(value=>this.baseChoice(value)) : [])])];
  }

  get isStructuredStep(): boolean {
    return ['ai_sales_authorization', 'project_sales_team', 'meta_lead_setup'].includes(this.question?.input_type || '');
  }

  get isMultiSelect(): boolean {
    return this.question?.input_type === 'multi_select';
  }

  choose(choice: string): void {
    if(this.disabled || this.answered)return;
    this.prepareSelection();
    if(this.question?.answer_actions?.[choice]?.kind === 'defer' && this.isMultiSelect) {
      this.deferred.emit(this.selectionWithDetails());return;
    }
    if(this.isAction(choice)){this.selectedValues.clear();this.selected.emit(choice);return;}
    if (!this.isMultiSelect) {
      this.selected.emit(choice);
      return;
    }
    if (this.selectedValues.has(choice)) this.selectedValues.delete(choice);
    else {
      if(this.question.exclusive_options?.includes(choice))this.selectedValues.clear();
      else for(const exclusive of this.question.exclusive_options || [])this.selectedValues.delete(exclusive);
      this.selectedValues.add(choice);
    }
  }

  baseChoice(value:string):string {return (this.question?.detail_options || []).find(label=>value.startsWith(label+':')) || value;}
  get detailChoices():string[] {return [...this.selectedValues].filter(value=>this.question?.detail_options?.includes(value));}
  get missingDetails():boolean {return this.detailChoices.some(value=>(this.optionDetails[value] || '').trim().length<10);}
  selectionWithDetails():string[] {return [...this.selectedValues].map(value=>this.question?.detail_options?.includes(value) && this.optionDetails[value]?.trim() ? value+': '+this.optionDetails[value].trim() : value);}
  isSelected(choice: string): boolean {
    return this.isMultiSelect ? this.selectedValues.has(choice) : choice === this.selectedChoice;
  }

  submitSelection(): void {
    this.prepareSelection();
    if (!this.selectedValues.size || this.disabled || this.answered || this.selectionConflict || this.missingDetails) return;
    this.selected.emit(this.selectionWithDetails());
  }
  get selectionConflict():boolean {return this.selectedValues.size>1 && (this.question?.exclusive_options || []).some(value=>this.selectedValues.has(value));}

  get suggestionLabel(): string {
    if (this.question.suggestion_origin === 'website') return 'Based on your website and confirmed information';
    if (this.question.suggestion_origin === 'confirmed_context') return 'Based on your confirmed answers';
    if (this.question.suggestion_origin === 'generic_fallback') return 'Starter suggestions';
    return '';
  }
}
