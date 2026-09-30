import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ModalComponent } from './modal';

describe('Modal', () => {
  let component: ModalComponent;
  let fixture: ComponentFixture<ModalComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ModalComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(ModalComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('constrains tall dialogs and exposes an internal scroll region', () => {
    fixture.componentRef.setInput('isOpen', true);
    fixture.componentRef.setInput('title', 'Responsive dialog');
    fixture.detectChanges();

    const overlay = fixture.nativeElement.querySelector('[role="dialog"]') as HTMLElement;
    const panel = overlay.querySelector('[tabindex="-1"]') as HTMLElement;
    const scrollRegion = overlay.querySelector('[data-modal-scroll-region]') as HTMLElement;
    expect(overlay.classList.contains('overflow-y-auto')).toBe(true);
    expect(panel.className).toContain('max-h-[calc(100dvh-2rem)]');
    expect(scrollRegion.classList.contains('overflow-y-auto')).toBe(true);
    expect(overlay.getAttribute('aria-labelledby')).toBe(component.titleId);
  });

  it('locks background scrolling while open and restores it after closing', () => {
    document.body.style.overflow = 'auto';
    component.isOpen = true;
    component.ngOnChanges({ isOpen: { currentValue: true, previousValue: false, firstChange: false, isFirstChange: () => false } });
    expect(document.body.style.overflow).toBe('hidden');

    component.isOpen = false;
    component.ngOnChanges({ isOpen: { currentValue: false, previousValue: true, firstChange: false, isFirstChange: () => false } });
    expect(document.body.style.overflow).toBe('auto');
  });

  it('emits close when Escape is pressed', () => {
    component.isOpen = true;
    const closeSpy = vi.spyOn(component.close, 'emit');
    component.handleDocumentKeydown(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(closeSpy).toHaveBeenCalledOnce();
  });
});
