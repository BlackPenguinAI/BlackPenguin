/**
 * P09.1 live Agent view: reconcile an open chat with the authoritative inbox.
 *
 * The existing component polls /sales-agent/conversations. When a lead is
 * removed on /app/leads, its conversation is removed by the backend, but the
 * old component kept the last selected object (and its messages) on screen.
 * Keep the original Agent behavior/template and clear only disappeared rows.
 */
import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, DoCheck } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import { AgentContextComponent } from '../../../shared/ui/agent-context/agent-context';
import { AgentComponent } from './agent';

@Component({
  selector: 'app-agent-p091',
  standalone: true,
  imports: [AgentContextComponent, CommonModule, FormsModule],
  templateUrl: './agent.html',
  styleUrls: ['./agent.scss'],
})
export class AgentP091Component extends AgentComponent implements DoCheck {
  constructor(http: HttpClient, cdr: ChangeDetectorRef, route: ActivatedRoute) {
    super(http, cdr, route);
  }

  ngDoCheck(): void {
    // Before the initial response, an empty array is not evidence of deletion.
    if (this.loading || !this.selected) return;
    if (this.conversations.some(row => row.id === this.selected.id)) return;

    // The active record disappeared from the authenticated backend listing.
    // Never leave stale messages or operational context in the Agent view.
    this.selected = null;
    this.messages = [];
    this.slots = [];
    this.selectedSlot = '';
    this.reviewNote = '';
    this.initialGenerationError = '';
    this.setupOpen = this.conversations.length === 0;
  }
}
