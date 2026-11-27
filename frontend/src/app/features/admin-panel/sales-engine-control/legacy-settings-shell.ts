import { Component } from '@angular/core';
import { AiSettingsPageComponent } from '../ai-settings/ai-settings-page/ai-settings-page';
import { ActivatedRoute } from '@angular/router';

/** Keep the complete original legacy/onboarding editor and its version history intact. */
@Component({
  selector: 'app-legacy-settings-shell',
  standalone: true,
  imports: [AiSettingsPageComponent],
  template: `<app-ai-settings-page [initialTab]="initialTab"></app-ai-settings-page>`
})
export class LegacySettingsShellComponent {
  constructor(private route: ActivatedRoute) {}
  get initialTab(): string { return this.route.snapshot.queryParamMap.get('tab') === 'ventas' ? 'ventas' : 'empresa'; }
}
