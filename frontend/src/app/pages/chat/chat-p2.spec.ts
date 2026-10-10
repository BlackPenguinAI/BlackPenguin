import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';

import { ChatComponent } from './chat';

describe('Company onboarding P2 interactions', () => {
  it('submits a suggested chip immediately', () => {
    vi.stubGlobal('localStorage', { getItem: () => 'en' });
    const component = new ChatComponent(
      { use: vi.fn() } as never,
      {} as never,
      { detectChanges: vi.fn() } as never,
      { isSupported: false } as never,
      {} as never,
    );
    const send = vi.spyOn(component, 'sendMessage').mockImplementation(() => undefined);

    component.chooseAnswer('Real-estate development', { id: 'question-1' } as never);

    expect(component.prompt).toBe('Real-estate development');
    expect(send).toHaveBeenCalledOnce();
  });
});
