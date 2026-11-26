import { Component } from '@angular/core';
import { AiSettingsPageComponent } from '../ai-settings/ai-settings-page/ai-settings-page';
import { SalesEngineControlComponent } from './sales-engine-control';

/** Keep the complete original legacy/onboarding editor and its version history intact. */
@Component({
  selector: 'app-legacy-settings-shell',
  standalone: true,
  imports: [AiSettingsPageComponent, SalesEngineControlComponent],
  template: `
    <div class="bp-page__container bp-page__container--form py-6">
      <app-sales-engine-control editor="langgraph"></app-sales-engine-control>
    </div>
    <app-ai-settings-page></app-ai-settings-page>
  `
})
export class LegacySettingsShellComponent {}
