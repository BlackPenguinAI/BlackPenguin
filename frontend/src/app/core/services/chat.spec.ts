import { TestBed } from '@angular/core/testing';

import { ChatService as Chat } from './chat';

describe('Chat', () => {
  let service: Chat;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(Chat);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
