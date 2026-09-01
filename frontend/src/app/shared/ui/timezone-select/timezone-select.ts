import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgSelectComponent } from '@ng-select/ng-select';

import { searchTimezone, TimezoneOption, timezoneOptions } from '../../../core/timezones';

@Component({
  selector: 'app-timezone-select',
  standalone: true,
  imports: [CommonModule, FormsModule, NgSelectComponent],
  templateUrl: './timezone-select.html',
  styleUrl: './timezone-select.scss',
})
export class TimezoneSelectComponent {
  @Input() value = 'UTC';
  @Input() disabled = false;
  @Input() compact = false;
  @Input() ariaLabel = 'Timezone';
  @Output() valueChange = new EventEmitter<string>();

  readonly options = timezoneOptions();
  readonly searchTimezone = (term: string, option: TimezoneOption) => searchTimezone(term, option);

  update(value: string | null): void {
    if (value) this.valueChange.emit(value);
  }
}
