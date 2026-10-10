import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';

import { ProjectChatComponent } from './project-chat';

function component(): ProjectChatComponent {
  return new ProjectChatComponent(
    {} as never,
    {} as never,
    { detectChanges: vi.fn() } as never,
    { isSupported: false } as never,
    {} as never,
  );
}

describe('ProjectChatComponent P2 interactions', () => {
  it('submits a suggested chip instead of only copying it into the composer', () => {
    const instance = component();
    const send = vi.spyOn(instance, 'sendMessage').mockImplementation(() => undefined);

    instance.chooseAnswer('Pre-sales', { id: 'question-1' } as never);

    expect(instance.prompt).toBe('Pre-sales');
    expect(send).toHaveBeenCalledOnce();
  });

  it('keeps cover choice provisional until the explicit confirmation action', () => {
    const instance = component();
    instance.selectCoverCandidate({ id: 'cover-1', kind: 'image' } as never);

    expect(instance.selectedCoverSourceId).toBe('cover-1');
  });
});
