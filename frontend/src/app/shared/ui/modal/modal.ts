import { Component, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './modal.html'
})
export class ModalComponent {
  @Input() isOpen: boolean = false;
  @Input() title?: string;
  @Input() subtitle?: string;
  @Input() variant: 'default' | 'danger' = 'default';
  @Input() maxWidthClass: string = 'max-w-md';
  @Input() showCloseButton: boolean = true;
  
  @Output() close = new EventEmitter<void>();
}