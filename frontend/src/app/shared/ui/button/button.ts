import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-button',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './button.html'
})
export class ButtonComponent {
  @Input() type: 'button' | 'submit' = 'button';
  @Input() variant: 'primary' | 'secondary' | 'ghost' | 'danger' = 'primary';
  @Input() isLoading: boolean = false;
  @Input() disabled: boolean = false;
  @Input() icon?: string;
  @Input() fullWidth: boolean = false;
  
  @Output() onClick = new EventEmitter<Event>();

  getButtonClasses(): string {
    let baseClass = 'font-semibold text-sm rounded-xl transition-all duration-300 flex items-center justify-center gap-2 focus:outline-none disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.98] ';
    
    baseClass += this.fullWidth ? 'w-full py-3 ' : 'px-6 py-2.5 ';

    switch (this.variant) {
      case 'primary':
        return baseClass + 'bg-white text-black hover:bg-secondary hover:text-white shadow-lg';
      case 'secondary':
        return baseClass + 'bg-secondary text-black hover:bg-yellow-500 shadow-[0_0_15px_rgba(234,179,8,0.2)]';
      case 'danger':
        return baseClass + 'bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500 hover:text-white';
      case 'ghost':
        return baseClass + 'bg-white/5 border border-white/5 text-gray-300 hover:bg-white/10 hover:text-white hover:border-white/20';
      default:
        return baseClass;
    }
  }
}