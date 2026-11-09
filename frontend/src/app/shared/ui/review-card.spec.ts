import { TestBed } from '@angular/core/testing';
import { Component, SimpleChange } from '@angular/core';
import { ReviewCardComponent } from './review-card';

@Component({standalone:true,imports:[ReviewCardComponent],template:`<app-review-card title="Review" [open]="open" [complete]="true" (openChange)="open=$event"><input value="Saved value"></app-review-card>`})
class ControlledHost { open=true; }

describe('ReviewCard optional controlled disclosure', () => {
  afterEach(() => TestBed.resetTestingModule());
  it('preserves legacy completion and revision defaults when not controlled', () => {
    const card=new ReviewCardComponent();card.complete=true;
    card.ngOnChanges({complete:new SimpleChange(false,true,false)});
    expect(card.expanded).toBe(false);
    card.toggle();expect(card.expanded).toBe(true);
    card.ngOnChanges({revision:new SimpleChange(1,2,false)});
    expect(card.expanded).toBe(false);
  });
  it('keeps a completed step open when its parent explicitly requests review', () => {
    const card=new ReviewCardComponent();card.complete=true;card.open=true;
    card.ngOnChanges({complete:new SimpleChange(false,true,false)});
    expect(card.expanded).toBe(true);
    card.open=false;card.complete=false;
    card.ngOnChanges({complete:new SimpleChange(true,false,false)});
    expect(card.expanded).toBe(false);
  });
  it('emits user toggles without destroying projected form values', async () => {
    await TestBed.configureTestingModule({imports:[ControlledHost]}).compileComponents();
    const fixture=TestBed.createComponent(ControlledHost);fixture.detectChanges();
    const input=fixture.nativeElement.querySelector('input') as HTMLInputElement;
    input.value='Unsaved selection';
    const toggle=fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    toggle.click();fixture.detectChanges();
    expect(fixture.componentInstance.open).toBe(false);
    expect(fixture.nativeElement.querySelector('input')).toBe(input);
    toggle.click();fixture.detectChanges();
    expect(fixture.componentInstance.open).toBe(true);
    expect(input.value).toBe('Unsaved selection');
  });
});
