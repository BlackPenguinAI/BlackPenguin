import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output, OnDestroy, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgSelectComponent } from '@ng-select/ng-select';

import { searchTimezone, TimezoneOption, timezoneOptions } from '../../../core/timezones';

let nextTimezoneSelectId = 0;

@Component({
  selector: 'app-timezone-select',
  standalone: true,
  imports: [CommonModule, FormsModule, NgSelectComponent],
  templateUrl: './timezone-select.html',
  styleUrl: './timezone-select.scss',
})
export class TimezoneSelectComponent implements OnDestroy {
  readonly inputId = 'bp-timezone-' + nextTimezoneSelectId++;
  @ViewChild(NgSelectComponent) select?: NgSelectComponent;
  @Input() value = 'UTC';
  @Input() disabled = false;
  @Input() compact = false;
  @Input() ariaLabel = 'Timezone';
  @Input() placeholder = 'Search Lima, Bogotá, America/Lima or UTC-5';
  private filterKey: string | null = null;
  @Input() set allowedZones(zones: readonly string[] | null) {
    const key = zones === null ? null : [...new Set(zones)].sort().join('|');
    if (key === this.filterKey) return;
    this.filterKey = key;
    this.options = timezoneOptions(new Date(), zones ?? undefined);
  }
  @Output() valueChange = new EventEmitter<string>();

  options = timezoneOptions();
  readonly searchTimezone = (term: string, option: TimezoneOption) => searchTimezone(term, option);

  private readonly closeOnViewportChange = (event: Event) => {
    const target = event.target;
    if (target instanceof Element && target.closest('ng-dropdown-panel.timezone-select')) return;
    this.select?.close();
  };
  opened(): void {
    document.addEventListener('scroll', this.closeOnViewportChange, true);
    window.addEventListener('resize', this.closeOnViewportChange);
  }
  closed(): void {
    document.removeEventListener('scroll', this.closeOnViewportChange, true);
    window.removeEventListener('resize', this.closeOnViewportChange);
  }
  ngOnDestroy(): void { this.closed(); }

  update(value: string | null): void {
    if (!this.disabled && value && this.options.some(option => option.value === value)) this.valueChange.emit(value);
  }
}
