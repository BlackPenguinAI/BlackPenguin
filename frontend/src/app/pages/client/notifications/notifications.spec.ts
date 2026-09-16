import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { NotificationsComponent } from './notifications';

describe('NotificationsComponent', () => {
  it('marks an unread notification before navigating to its safe internal action', () => {
    const http = {
      get: vi.fn().mockReturnValue(of([])),
      post: vi.fn().mockReturnValue(of({})),
    } as any;
    const router = { navigateByUrl: vi.fn() } as any;
    const component = new NotificationsComponent(http, router, { markForCheck: vi.fn() } as any);
    component.open({ id: 'notification-1', read_at: null, action_url: '/app/leads?lead=lead-1' });
    expect(http.post).toHaveBeenCalledWith(expect.stringContaining('/notification-1/read'), {});
    expect(router.navigateByUrl).toHaveBeenCalledWith('/app/leads?lead=lead-1');
  });
});
