import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TimezoneSelectComponent } from './timezone-select';

afterEach(() => {TestBed.resetTestingModule();vi.restoreAllMocks();});

describe('Searchable timezone overlay', () => {
  it('places the searchable list outside a clipped card and emits the exact selected IANA value', async () => {
    const fixture=TestBed.createComponent(TimezoneSelectComponent);
    fixture.componentRef.setInput('allowedZones',['America/New_York','America/Chicago']);
    fixture.componentRef.setInput('value','');
    fixture.detectChanges();await fixture.whenStable();
    fixture.nativeElement.style.overflow='hidden';
    const emitted=vi.fn();fixture.componentInstance.valueChange.subscribe(emitted);
    const input=fixture.nativeElement.querySelector('input[role="combobox"]') as HTMLInputElement;
    expect(input.id).toBe(fixture.componentInstance.inputId);
    expect(fixture.nativeElement.querySelector('label').getAttribute('for')).toBe(input.id);
    expect(fixture.nativeElement.querySelector('label').textContent).toBe('Timezone');
    input.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
    fixture.componentInstance.select!.open();fixture.detectChanges();await fixture.whenStable();
    const panel=document.body.querySelector('ng-dropdown-panel.timezone-select')!;
    expect(panel).toBeTruthy();expect(panel.parentElement).toBe(document.body);
    expect(fixture.nativeElement.contains(panel)).toBe(false);
    input.value='Chicago';input.dispatchEvent(new Event('input',{bubbles:true}));
    fixture.detectChanges();await fixture.whenStable();
    expect(panel.textContent).toContain('America/Chicago');
    expect(panel.textContent).not.toContain('America/New_York');
    const option=panel.querySelector('.ng-option') as HTMLElement;
    option.click();fixture.detectChanges();await fixture.whenStable();
    expect(emitted).toHaveBeenCalledWith('America/Chicago');
    expect(document.body.querySelector('ng-dropdown-panel.timezone-select')).toBeNull();
  });

  it('keeps list scrolling usable but closes on outside scrolling or resize and cleans up', async () => {
    const fixture=TestBed.createComponent(TimezoneSelectComponent);
    fixture.componentRef.setInput('allowedZones',['America/Lima']);fixture.detectChanges();await fixture.whenStable();
    fixture.componentInstance.select!.open();fixture.detectChanges();await fixture.whenStable();
    const panel=document.body.querySelector('ng-dropdown-panel.timezone-select')!;
    panel.querySelector('.scroll-host')!.dispatchEvent(new Event('scroll'));
    expect(document.body.contains(panel)).toBe(true);
    fixture.nativeElement.dispatchEvent(new Event('scroll'));
    fixture.detectChanges();expect(document.body.querySelector('ng-dropdown-panel.timezone-select')).toBeNull();
    fixture.componentInstance.select!.open();fixture.detectChanges();await fixture.whenStable();
    window.dispatchEvent(new Event('resize'));fixture.detectChanges();
    expect(document.body.querySelector('ng-dropdown-panel.timezone-select')).toBeNull();
    fixture.componentInstance.select!.open();fixture.detectChanges();await fixture.whenStable();
    await new Promise(resolve=>setTimeout(resolve,30));
    fixture.destroy();expect(document.body.querySelector('ng-dropdown-panel.timezone-select')).toBeNull();
  });

  it('restricts onboarding choices without changing the full profile list or accepting arbitrary text', () => {
    const component=new TimezoneSelectComponent();
    const emit=vi.fn();component.valueChange.subscribe(emit);
    component.allowedZones=['America/Lima','Invalid/Zone','America/Lima'];
    expect(component.options.map(option=>option.value)).toEqual(['America/Lima']);
    component.update('Europe/Paris');component.update('not an IANA value');expect(emit).not.toHaveBeenCalled();
    component.update('America/Lima');expect(emit).toHaveBeenCalledWith('America/Lima');
    component.allowedZones=null;
    expect(component.options.some(option=>option.value==='Europe/Paris')).toBe(true);
    component.disabled=true;emit.mockClear();component.update('America/Lima');expect(emit).not.toHaveBeenCalled();
  });
});
