import { Component, ElementRef, EventEmitter, HostListener, Input, Output, forwardRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

export interface SelectOption {
  label: string;
  value: string | number | null;
  disabled?: boolean;
}

@Component({
  selector: 'app-select',
  standalone: true,
  imports: [CommonModule],
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => SelectComponent),
      multi: true
    }
  ],
  templateUrl: './select.html',
  styleUrl: './select.scss'
})
export class SelectComponent implements ControlValueAccessor {
  @Input() label?: string;
  @Input() placeholder = 'Select';
  @Input() options: SelectOption[] = [];
  @Input() disabled = false;

  @Output() selectionChange = new EventEmitter<string | number | null>();

  value: string | number | null = '';
  isOpen = false;

  private onChange: (value: string | number | null) => void = () => {};
  private onTouched: () => void = () => {};

  constructor(private elementRef: ElementRef<HTMLElement>) {}

  get selectedLabel(): string {
    return this.options.find((option) => option.value === this.value)?.label || this.placeholder;
  }

  @HostListener('document:click', ['$event'])
  closeFromOutside(event: Event) {
    if (!this.elementRef.nativeElement.contains(event.target as Node)) {
      this.close();
    }
  }

  @HostListener('document:keydown.escape')
  closeOnEscape() {
    this.close();
  }

  toggle() {
    if (this.disabled) {
      return;
    }

    this.isOpen = !this.isOpen;
    this.onTouched();
  }

  selectOption(option: SelectOption) {
    if (option.disabled) {
      return;
    }

    this.value = option.value;
    this.onChange(option.value);
    this.selectionChange.emit(option.value);
    this.close();
  }

  writeValue(value: string | number | null): void {
    this.value = value ?? '';
  }

  registerOnChange(fn: (value: string | number | null) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled = isDisabled;
  }

  private close() {
    this.isOpen = false;
  }
}
