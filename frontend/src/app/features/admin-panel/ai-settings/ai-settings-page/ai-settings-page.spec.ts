import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { AiSettingsPageComponent } from './ai-settings-page';

describe('AiSettingsPageComponent', () => {
  it('exposes a structured sales prompt pack', () => {
    const component = new AiSettingsPageComponent({} as any, {} as any, {} as any);
    component.activeTab = 'ventas';
    expect(component.activeAgent.stage_prompts).toEqual({});
    expect(component.activeAgent.scoring_config).toEqual({});
  });

  it('loads prompt history lazily and keeps stable prompt key arrays', () => {
    const service = {
      getSalesPromptVersions: vi.fn().mockReturnValue(of({
        items: [{ id: 'v1', version: 1 }], total: 1, page: 1, page_size: 20,
      })),
    };
    const component = new AiSettingsPageComponent(
      service as any, {} as any, { detectChanges: vi.fn() } as any,
    );
    expect(service.getSalesPromptVersions).not.toHaveBeenCalled();
    component.setTab('ventas');
    expect(service.getSalesPromptVersions).toHaveBeenCalledTimes(1);
    component.setTab('ventas');
    expect(service.getSalesPromptVersions).toHaveBeenCalledTimes(1);
    expect(component.promptVersions).toHaveLength(1);
  });
});
