import '@angular/compiler';
import { describe, expect, it } from 'vitest';
import { AiSettingsPageComponent } from './ai-settings-page';

describe('AiSettingsPageComponent', () => {
  it('exposes a structured sales prompt pack', () => {
    const component = new AiSettingsPageComponent({} as any, {} as any, {} as any);
    component.activeTab = 'ventas';
    expect(component.activeAgent.stage_prompts).toEqual({});
    expect(component.activeAgent.scoring_config).toEqual({});
  });
});
