import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-glass-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './glass-card.html'
})
export class GlassCardComponent {
  @Input() title?: string;
  @Input() icon?: string;
  @Input() paddingClass: string = 'p-6 md:p-8';
}