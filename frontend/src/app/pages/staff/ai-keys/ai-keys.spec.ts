import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AiKeys } from './ai-keys';

describe('AiKeys', () => {
  let component: AiKeys;
  let fixture: ComponentFixture<AiKeys>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AiKeys],
    }).compileComponents();

    fixture = TestBed.createComponent(AiKeys);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
