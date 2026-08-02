import { ComponentFixture, TestBed } from '@angular/core/testing';

import { WaitlistPage } from './waitlist-page';

describe('WaitlistPage', () => {
  let component: WaitlistPage;
  let fixture: ComponentFixture<WaitlistPage>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [WaitlistPage],
    }).compileComponents();

    fixture = TestBed.createComponent(WaitlistPage);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
