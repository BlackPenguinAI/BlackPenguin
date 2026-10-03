import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { routes } from './app.routes';

describe('application routes', () => {
  it('keeps agent settings hidden and redirects saved links to the live agent', () => {
    const app = routes.find(route => route.path === 'app');
    const agentSettings = app?.children?.find(route => route.path === 'agent-settings');

    expect(agentSettings?.redirectTo).toBe('agent');
    expect(agentSettings?.pathMatch).toBe('full');
    expect(agentSettings?.loadComponent).toBeUndefined();
  });
});
