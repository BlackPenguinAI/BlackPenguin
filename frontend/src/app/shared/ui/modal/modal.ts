import {
  Component, ElementRef, EventEmitter, HostListener, Input, OnChanges,
  OnDestroy, Output, SimpleChanges, ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';

let modalInstanceSequence = 0;

@Component({
  selector: 'app-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './modal.html'
})
export class ModalComponent implements OnChanges, OnDestroy {
  @Input() isOpen: boolean = false;
  @Input() title?: string;
  @Input() subtitle?: string;
  @Input() variant: 'default' | 'danger' = 'default';
  @Input() maxWidthClass: string = 'max-w-md';
  @Input() showCloseButton: boolean = true;
  readonly titleId = `bp-modal-title-${++modalInstanceSequence}`;

  @Output() close = new EventEmitter<void>();

  private panel?: ElementRef<HTMLElement>;
  private previouslyFocusedElement: HTMLElement | null = null;
  private previousBodyOverflow: string | null = null;

  @ViewChild('dialogPanel')
  set dialogPanel(value: ElementRef<HTMLElement> | undefined) {
    this.panel = value;
    if (value && this.isOpen) {
      queueMicrotask(() => this.focusInitialControl());
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    const openChange = changes['isOpen'];
    if (!openChange) return;
    if (openChange.currentValue) this.prepareOpenDialog();
    else this.restorePageState();
  }

  ngOnDestroy(): void {
    this.restorePageState();
  }

  @HostListener('document:keydown', ['$event'])
  handleDocumentKeydown(event: KeyboardEvent): void {
    if (!this.isOpen) return;
    if (event.key === 'Escape' && this.showCloseButton) {
      event.preventDefault();
      this.close.emit();
      return;
    }
    if (event.key === 'Tab') this.keepFocusInsideDialog(event);
  }

  private prepareOpenDialog(): void {
    if (typeof document === 'undefined') return;
    this.previouslyFocusedElement = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    if (this.previousBodyOverflow === null) {
      this.previousBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
    }
  }

  private restorePageState(): void {
    if (typeof document === 'undefined' || this.previousBodyOverflow === null) return;
    document.body.style.overflow = this.previousBodyOverflow;
    this.previousBodyOverflow = null;
    const target = this.previouslyFocusedElement;
    this.previouslyFocusedElement = null;
    if (target?.isConnected) queueMicrotask(() => target.focus());
  }

  private focusableElements(): HTMLElement[] {
    const panel = this.panel?.nativeElement;
    if (!panel) return [];
    return Array.from(panel.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), ' +
      'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter(element => !element.hasAttribute('hidden') && element.offsetParent !== null);
  }

  private focusInitialControl(): void {
    const panel = this.panel?.nativeElement;
    if (!panel || !this.isOpen) return;
    const autofocus = panel.querySelector<HTMLElement>('[autofocus]');
    (autofocus || this.focusableElements()[0] || panel).focus();
  }

  private keepFocusInsideDialog(event: KeyboardEvent): void {
    const panel = this.panel?.nativeElement;
    if (!panel) return;
    const controls = this.focusableElements();
    if (!controls.length) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = controls[0];
    const last = controls[controls.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !panel.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }
}
