import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges } from '@angular/core';

interface SourceRef { message_id: string; at: string | null; }
interface Property { id: string; name: string; kind: string; price: number | null; price_kind: string; currency: string | null; bedrooms: number | null; }
interface Budget { mode: string; currency: string | null; minimum_usd: number | null; maximum_usd: number | null; target_usd: number | null; exact_price_usd: number | null; }
interface Bedrooms { mode: string; minimum: number | null; maximum: number | null; preferred: number | null; }
interface Fact { value: string | number | Record<string, string | number | null> | null; status: string; source: string; evidence: SourceRef | null; at: string | null; }
interface Proposal { property: Property | null; date: string | null; time: string | null; timezone: string | null; status: string; kind?: string; expires_at: string | null; recap_message_id?: string | null; }
interface Visit { id: string; property_name: string | null; status: string; confirmation_status: string; calendar_status: string; starts_at: string | null; timezone: string | null; duration_minutes: number | null; address: string | null; specialist: string | null; active: boolean; }
interface Material { asset_id: string; name: string | null; tags: string[]; status: string; message_id?: string | null; access_status: string; at?: string | null; engine?: string; }
interface Observation { order: number; tool: string; status: string; error_code: string | null; }
interface Activity { kind: string; at: string | null; ended_at?: string | null; message_id?: string | null; engine?: string; status: string; direction?: string; mode?: string; error_code?: string | null; revision?: number; operation?: string; result?: string; tools?: Observation[]; }
export interface HermesInspectorView {
  version: string; scope: { conversation_id: string; company_id: string; project_id: string; lead_id: string };
  routing: { active_sales_engine: string | null; effective_sales_engine: string | null; target_default_engine: string; hermes_live_ready: boolean; error_code: string | null };
  has_state: boolean; historical_state: boolean; revision: number | null; updated_at: string | null; engine_version: string | null;
  last_engine: string; last_run_engine: string; conversation_engine: string; channel: string; project_name: string | null; timezone: string | null;
  phase: string | null; phase_source: string | null; focus: Property | null; focus_status: string; presented_properties: Property[];
  primary_preferences: { revision: number | null; source: SourceRef | null; budget: Budget; bedrooms: Bedrooms };
  crm_facts: Record<string,Fact>; active_search: { scope: string; criteria: Record<string, unknown>; matches: Property[]; source: SourceRef | null; match_count: number | null } | null;
  property_filters: Record<string,unknown>; visit_draft: Proposal | null; confirmation: Proposal | null; visit_planning_paused: boolean;
  slot_offer: { slots: { date: string; time: string }[]; expires_at: string | null; timezone: string | null; property: Property | null; status: string } | null;
  visits: Visit[]; materials: Material[]; operations: Activity[]; timeline: Activity[];
}

type InspectorTab = 'profile' | 'property' | 'visits' | 'activity';

@Component({ selector: 'app-hermes-inspector', standalone: true, imports: [CommonModule],
  template: `<section *ngIf="view as h" class="inspector" aria-label="Hermes conversation inspector">
  <header class="inspector-heading">
    <div><h3>Conversation Inspector</h3><small>Read-only · Updated with Agent activity</small></div>
    <span class="engine-chip">{{engine(h.last_run_engine)}}</span>
  </header>
  <dl class="runtime-grid">
    <div><dt>Selected live engine</dt><dd>{{engine(h.routing.active_sales_engine)}}</dd></div>
    <div><dt>Last recorded turn</dt><dd>{{engine(h.last_run_engine)}}</dd></div>
    <div><dt>Last accepted response</dt><dd>{{engine(h.last_engine)}}</dd></div>
    <div><dt>Hermes state revision</dt><dd>{{h.revision ?? 'Not recorded'}}</dd></div>
  </dl>
  <p *ngIf="!h.routing.hermes_live_ready" class="note">Hermes live activation is not certified. Viewing this inspector does not change the active engine.</p>
  <p *ngIf="h.channel==='simulation'" class="note">Simulation · No live provider delivery is implied.</p>
  <p *ngIf="h.historical_state" class="warning">Historical Hermes context — not the current engine's active offers.</p>
  <p *ngIf="!h.has_state" class="note">No current Hermes state recorded. Shared CRM facts, visits and recent activity are shown when available.</p>
  <p *ngIf="h.has_state" class="phase"><span>Conversation phase</span><strong>{{text(h.phase)}}<small *ngIf="h.phase_source==='observed'"> · observed</small></strong><small *ngIf="h.updated_at">Updated {{time(h.updated_at,h.timezone)}} · {{h.timezone || 'UTC'}}</small></p>
  <nav class="tabs" aria-label="Inspector sections">
    <button *ngFor="let item of tabs" type="button" [class.active]="tab===item.id" [attr.aria-pressed]="tab===item.id" (click)="tab=item.id">{{item.label}}</button>
  </nav>
  <div *ngIf="tab==='profile'" class="section-stack">
    <article *ngIf="h.has_state"><h4>Primary buyer preferences</h4><small>Hermes persisted state · not verified financing</small>
      <dl class="facts">
        <div><dt>Budget interpretation</dt><dd>{{text(h.primary_preferences.budget.mode)}}</dd></div>
        <div><dt>Minimum budget</dt><dd>{{money(h.primary_preferences.budget.minimum_usd,h.primary_preferences.budget.currency)}}</dd></div>
        <div><dt>Maximum budget</dt><dd>{{money(h.primary_preferences.budget.maximum_usd,h.primary_preferences.budget.currency)}}</dd></div>
        <div><dt>Target budget</dt><dd>{{money(h.primary_preferences.budget.target_usd,h.primary_preferences.budget.currency)}}</dd></div>
        <div *ngIf="h.primary_preferences.budget.exact_price_usd!=null"><dt>Exact listing price</dt><dd>{{money(h.primary_preferences.budget.exact_price_usd,h.primary_preferences.budget.currency)}}</dd></div>
        <div><dt>Bedroom criteria</dt><dd>{{bedrooms(h.primary_preferences.bedrooms)}}</dd></div>
      </dl>
      <button *ngIf="h.primary_preferences.source as source" type="button" class="evidence" (click)="showEvidence(source.message_id)">Last preference update · {{time(source.at,h.timezone)}}</button>
      <small *ngIf="!h.primary_preferences.source">No scoped source message recorded for the latest preference update.</small>
    </article>
    <article><h4>Shared CRM facts</h4><small>Recorded separately from Hermes preferences</small>
      <dl class="facts">
        <div><dt>Purchase timeframe</dt><dd>{{fact(h.crm_facts['purchase_timeline'])}} <small>· {{text(h.crm_facts['purchase_timeline']?.status)}}</small></dd></div>
        <div><dt>Registered budget</dt><dd>{{fact(h.crm_facts['budget'])}} <small>· {{text(h.crm_facts['budget']?.status)}}</small></dd></div>
        <div><dt>Registered bedrooms</dt><dd>{{fact(h.crm_facts['bedrooms'])}} <small>· {{text(h.crm_facts['bedrooms']?.status)}}</small></dd></div>
      </dl>
      <button *ngIf="h.crm_facts['purchase_timeline']?.evidence as source" type="button" class="evidence" (click)="showEvidence(source.message_id)">Purchase timeframe source · {{time(source.at,h.timezone)}}</button>
    </article>
    <article *ngIf="h.active_search as search"><h4>{{search.scope==='temporary'?'Temporary property search':'Recorded property search'}}</h4>
      <p *ngIf="search.scope==='temporary'" class="note">Primary preferences preserved.</p>
      <dl class="facts"><div *ngFor="let criterion of filterEntries(search.criteria)"><dt>{{criterion.label}}</dt><dd>{{criterion.value}}</dd></div></dl>
      <p *ngIf="search.match_count!=null">{{search.match_count}} results at last search</p>
      <button *ngIf="search.source as source" type="button" class="evidence" (click)="showEvidence(source.message_id)">Search source · {{time(source.at,h.timezone)}}</button>
      <small>Historical results, not a fresh inventory check.</small>
    </article>
    <article *ngIf="filterEntries(h.property_filters).length"><h4>Recorded property filters</h4><dl class="facts"><div *ngFor="let criterion of filterEntries(h.property_filters)"><dt>{{criterion.label}}</dt><dd>{{criterion.value}}</dd></div></dl></article>
  </div>
  <div *ngIf="tab==='property'" class="section-stack">
    <article><h4>{{h.historical_state?'Last Hermes property focus':'Property focus'}}</h4><small>{{h.project_name}}</small>
      <ng-container *ngIf="h.focus as p; else noFocus"><h5>{{p.name}}</h5><dl class="facts"><div><dt>Bedrooms</dt><dd>{{p.bedrooms ?? 'Not recorded'}}</dd></div><div><dt>{{p.price_kind==='starting'?'Starting price':'Listing price'}}</dt><dd>{{money(p.price,p.currency)}}</dd></div></dl><small>Approved catalog snapshot · availability not guaranteed.</small></ng-container>
      <ng-template #noFocus><p>{{h.focus_status==='ambiguous'?'Property reference is ambiguous':h.focus_status==='not_in_approved_catalog'?'Property no longer resolves in the approved catalog':'No property selected'}}</p></ng-template>
    </article>
    <article *ngIf="h.presented_properties.length"><h4>Previously presented options</h4><ol><li *ngFor="let p of h.presented_properties">{{p.name}}</li></ol><small>Previously accepted reply, not a fresh search.</small></article>
    <article><h4>Materials</h4><small>Approved catalog for focus and recent scoped access receipts. Issuance is not delivery.</small>
      <p *ngIf="!h.materials.length">No matching catalog items or recent receipts recorded.</p>
      <div class="entry" *ngFor="let m of h.materials"><strong>{{m.name || 'Material'}}</strong><small>{{m.tags.join(' · ')}}</small><span>{{materialStatus(m)}}</span><small>{{text(m.access_status)}}<ng-container *ngIf="m.engine"> · {{engine(m.engine)}}</ng-container></small><button *ngIf="m.message_id" class="evidence" type="button" (click)="showEvidence(m.message_id)">View receipt in activity</button></div>
    </article>
  </div>
  <div *ngIf="tab==='visits'" class="section-stack">
    <article><h4>Visit planning</h4><p *ngIf="h.visit_planning_paused" class="warning">Visit planning paused. Availability must be checked again.</p>
      <ng-container *ngIf="h.visit_draft as v"><p><strong>{{v.property?.name || 'Property not selected'}}</strong></p><p>{{v.date || 'Date not selected'}} · {{v.time || 'Time not selected'}} · {{v.timezone || 'Timezone not recorded'}}</p><p>Draft: {{text(v.status)}}</p></ng-container>
      <ng-container *ngIf="h.confirmation as p"><div class="entry"><strong>{{text(p.kind)}} · {{text(p.status)}}</strong><span>{{p.property?.name || 'Property not resolved'}}</span><span>{{p.date || 'Date not recorded'}} · {{p.time || 'Time not recorded'}} · {{p.timezone || 'Timezone not recorded'}}</span><small *ngIf="p.expires_at">Expires {{time(p.expires_at,h.timezone)}} · {{h.timezone || 'UTC'}}</small><button *ngIf="p.recap_message_id" class="evidence" type="button" (click)="showEvidence(p.recap_message_id)">View recap receipt</button></div></ng-container>
      <small>A draft or confirmation request is not a booked appointment.</small>
    </article>
    <article *ngIf="h.slot_offer as offer"><h4>Last calendar check</h4><p>{{text(offer.status)}} · {{offer.property?.name || 'Property not resolved'}}</p><p *ngFor="let slot of offer.slots">{{slot.date}} · {{slot.time}} ({{offer.timezone || 'Timezone not recorded'}})</p><small>Recorded availability check, not necessarily shown to the lead. Revalidate before booking.</small></article>
    <article><h4>Recorded appointments</h4><small>Shared CRM · independent of property enquiry</small><p *ngIf="!h.visits.length">No visits recorded for this project and lead.</p>
      <div class="entry" *ngFor="let v of h.visits"><strong>{{v.property_name || 'Property not recorded'}}</strong><span>{{time(v.starts_at,v.timezone)}} · {{v.timezone || 'UTC'}}</span><span>{{text(v.status)}}<ng-container *ngIf="v.active"> · active</ng-container> · {{v.duration_minutes ?? 'Unknown'}} min</span><small>{{v.address || 'Address not recorded'}}</small><small>{{v.specialist || 'Specialist not recorded'}}</small><small>Calendar: {{text(v.calendar_status)}}</small></div>
    </article>
    <article *ngIf="h.operations.length"><h4>Native operation receipts</h4><div class="entry" *ngFor="let op of h.operations"><strong>{{text(op.operation)}} · {{text(op.status)}}</strong><small>{{time(op.at,h.timezone)}} · {{text(op.result)}}</small></div></article>
  </div>
  <div *ngIf="tab==='activity'" class="section-stack">
    <article><h4>Recent activity</h4><small>Newest first · {{h.timezone || 'UTC'}} · bounded history</small>
      <p *ngIf="selectedEvidence&&!evidenceVisible" class="note">The source is outside the recent activity window. It remains in the conversation history.</p>
      <p *ngIf="!h.timeline.length">No scoped activity recorded.</p>
      <div class="entry activity" *ngFor="let event of h.timeline" [class.highlight]="event.kind==='message'&&!!selectedEvidence&&event.message_id===selectedEvidence">
        <strong>{{activityTitle(event)}}</strong><small>{{time(event.at,h.timezone)}}<ng-container *ngIf="event.ended_at"> → {{time(event.ended_at,h.timezone)}}</ng-container></small>
        <span>{{text(event.status)}}</span><a *ngIf="event.kind==='message' && event.message_id" [href]="'#agent-message-'+event.message_id" class="evidence">Locate message in chat</a><small *ngIf="event.error_code" class="warning">{{event.error_code}}</small>
        <div *ngIf="event.tools?.length" class="tools"><small>Tool observations in recorded order · within this turn, individual timestamps not recorded</small><div *ngFor="let tool of event.tools"><strong>{{tool.order}}. {{text(tool.tool)}}</strong><small>{{text(tool.status)}}<ng-container *ngIf="tool.error_code"> · {{tool.error_code}}</ng-container></small></div></div>
        <small *ngIf="event.kind==='operation'">Result: {{text(event.result)}}</small>
      </div>
    </article>
  </div>
  <footer>Read-only · No model calls, message sending or operation retries from this inspector.</footer>
</section>
`, styles: [`:host{display:block;min-width:0}.inspector{border:1px solid #66532b;background:#151515;border-radius:12px;margin:12px 0;padding:12px;overflow-wrap:anywhere;color:#f4f4f4;font-size:12px;container-type:inline-size}.inspector-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap}.inspector h3{font-size:15px;margin:0 0 3px}.inspector small,.inspector footer{color:#b8b8b8;line-height:1.45}.engine-chip{background:#272116;border:1px solid #776239;color:#f2cf7b;border-radius:6px;padding:4px 7px;font-weight:600}.runtime-grid,.facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:10px 0}.runtime-grid div,.facts div{min-width:0}.runtime-grid dt,.facts dt,.phase span{font-size:11px;color:#b8b8b8}.runtime-grid dd,.facts dd{margin:3px 0 0;font-weight:600}.note,.warning{border-left:2px solid #777;background:#222;padding:7px 9px;margin:8px 0;font-size:11px;line-height:1.5}.warning{border-color:#e9ad00;background:#30271a;color:#f4d083}.phase{display:flex;flex-direction:column;gap:3px;border-top:1px solid #444;padding-top:9px}.phase strong{color:#f1c75b;text-transform:capitalize}.tabs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px;margin:12px 0}.tabs button,.evidence{font:inherit;min-height:36px;border:1px solid #484848;border-radius:6px;background:#1e1e1e;color:#e7e7e7;padding:6px 8px;cursor:pointer;text-align:left}.tabs button{text-align:center}.tabs button.active{border-color:#e9ad00;color:#f2cf7b;background:#2c2518;font-weight:600}.tabs button:focus-visible,.evidence:focus-visible{outline:2px solid #e9ad00;outline-offset:2px}.section-stack{display:grid;gap:8px}.section-stack article{border:1px solid #383838;border-radius:9px;background:#191919;padding:10px;min-width:0}.section-stack h4{font-size:13px;color:#f1c75b;margin:0 0 5px}.section-stack h5{font-size:16px;margin:7px 0}.section-stack p{margin:7px 0;line-height:1.45}.section-stack ol{padding-left:20px;margin:6px 0}.entry{display:flex;flex-direction:column;gap:3px;border-top:1px solid #383838;padding:8px 0 3px;margin-top:8px}.entry strong{font-weight:600}.entry.highlight{outline:2px solid #e9ad00;outline-offset:3px;background:#30271a}.tools{margin:5px 0 0;padding:7px;border-left:2px solid #686868;display:grid;gap:5px}.tools div{display:flex;flex-direction:column;gap:2px}.evidence{text-decoration:none;display:inline-block;color:#f2cf7b;margin:6px 0 0;max-width:100%;font-size:11px}.inspector footer{font-size:10px;border-top:1px solid #383838;padding-top:8px;margin-top:10px}@container(max-width:300px){.runtime-grid,.facts{grid-template-columns:1fr}.tabs{grid-template-columns:repeat(2,minmax(0,1fr))}}
`] })
export class HermesInspectorComponent implements OnChanges {
  @Input() inspector: HermesInspectorView | null = null;
  @Input() conversationId = '';
  tab: InspectorTab = 'profile';
  readonly tabs: {id: InspectorTab; label: string}[] = [
    {id:'profile',label:'Profile'}, {id:'property',label:'Property'}, {id:'visits',label:'Visits'}, {id:'activity',label:'Activity'},
  ];
  selectedEvidence: string | null = null;
  private identity = '';
  ngOnChanges(): void {
    const s=this.view?.scope;
    const next=s?`${s.company_id}:${s.project_id}:${s.lead_id}:${s.conversation_id}`:'';
    if(next!==this.identity){this.identity=next;this.tab='profile';this.selectedEvidence=null;}
  }
  get view(): HermesInspectorView | null {
    const h=this.inspector;
    return h?.version==='hermes-conversation-inspector/1.0' && h.scope?.conversation_id===this.conversationId ? h : null;
  }
  text(value: string | null | undefined): string { return value ? value.replaceAll('_',' ') : 'Not captured'; }
  engine(value: string | null | undefined): string {
    switch(value){case 'hermes':return 'Hermes';case 'langgraph':return 'LangGraph';case 'hermes_control':return 'Hermes · control';case 'hermes_scheduled':return 'Hermes · scheduled';case 'lead':return 'Lead';case 'human':return 'Company team';default:return 'Not attributed';}
  }
  money(value: number | null | undefined, currency: string | null | undefined): string {
    if(value==null || !Number.isFinite(value))return 'Not captured';
    if(!currency)return `${new Intl.NumberFormat('en-US').format(value)} (currency not recorded)`;
    try{return new Intl.NumberFormat('en-US',{style:'currency',currency,currencyDisplay:'code',maximumFractionDigits:2}).format(value);}
    catch{return `${value} ${currency}`;}
  }
  bedrooms(value: Bedrooms): string {
    const n=(v:number|null)=>v==null?'Not captured':String(v);
    switch(value.mode){case 'exact':return value.preferred==null?'Not captured':`Exactly ${value.preferred}`;case 'minimum':return value.minimum==null?'Not captured':`At least ${value.minimum}`;case 'maximum':return value.maximum==null?'Not captured':`At most ${value.maximum}`;case 'range':return `${n(value.minimum)}–${n(value.maximum)}`;case 'preferred':return value.preferred==null?'Not captured':`Prefer ${value.preferred}`;case 'any':return 'Any';default:return 'Not captured';}
  }
  fact(value: Fact | undefined): string {
    if(!value || value.value==null)return 'Not captured';
    if(typeof value.value==='object')return Object.entries(value.value).filter(([,v])=>v!=null).map(([k,v])=>`${this.text(k)}: ${v}`).join(' · ')||'Not captured';
    return String(value.value);
  }
  filterEntries(value: Record<string,unknown> | null | undefined): {label:string;value:string}[] {
    return Object.entries(value||{}).filter(([,v])=>v!=null).map(([key,v])=>({label:this.text(key),value:Array.isArray(v)?v.join(' or '):typeof v==='boolean'?(v?'Yes':'No'):typeof v==='number'?new Intl.NumberFormat('en-US',{maximumFractionDigits:3}).format(v):String(v)}));
  }
  showEvidence(ref: string | null | undefined): void { if(ref){this.selectedEvidence=ref;this.tab='activity';} }
  get evidenceVisible(): boolean { return !!this.selectedEvidence && !!this.view?.timeline.some(e=>e.kind==='message'&&e.message_id===this.selectedEvidence); }
  activityTitle(e: Activity): string {
    switch(e.kind){case 'message':return `${this.engine(e.engine)} · ${e.direction==='inbound'?'Inbound':'Outbound'} message`;case 'run':return `${this.engine(e.engine)} · Agent turn${e.mode==='simulation'?' (simulation)':''}`;case 'state':return `Hermes · State revision ${e.revision ?? 'unknown'}`;case 'operation':return `Hermes · ${this.text(e.operation)} operation`;case 'job':return 'Inbound work';default:return 'Recorded activity';}
  }
  time(value:string|null|undefined, zone:string|null|undefined):string {
    if(!value)return 'Time not recorded';
    try{const d=new Date(value);if(!Number.isFinite(d.getTime()))return 'Time not recorded';return new Intl.DateTimeFormat('en-GB',{timeZone:zone||'UTC',year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(d);}
    catch{return 'Time not recorded';}
  }
  materialStatus(m:Material):string {
    switch(m.status){case 'approved_catalog':return 'Approved catalog · no recorded share';case 'issued_not_sent':return 'Access issued · not sent';case 'provider_accepted':return 'Provider accepted · delivery not confirmed';case 'delivered':return 'Delivery recorded';case 'queued':case 'sending':return 'Awaiting provider receipt';case 'unknown':return 'Receipt not verified';default:return this.text(m.status);}
  }
}
