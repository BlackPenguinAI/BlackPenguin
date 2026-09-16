import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({ selector: 'app-agent-settings', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './agent-settings.html', styleUrl: './agent-settings.scss' })
export class AgentSettingsComponent implements OnInit {
  projects: any[] = []; projectId = ''; guidance: any[] = []; kpis: any = null; error = ''; success = ''; saving = false;
  readonly canEdit = ['admin', 'assistant'].includes(typeof localStorage === 'undefined' ? '' : localStorage.getItem('bp_role') || '');
  readonly days = [{id:0,label:'MON'},{id:1,label:'TUE'},{id:2,label:'WED'},{id:3,label:'THU'},{id:4,label:'FRI'},{id:5,label:'SAT'},{id:6,label:'SUN'}];
  policy: any = { timezone: 'America/Lima', is_enabled: true, enforce_manual_messages: false, weekly_windows: {}, blackout_dates: [] };
  blackoutText = '';
  kpiTarget: any = { response_rate_percent: 30, conversation_turns_min: 2, conversation_turns_max: 12 };
  draft: any = { kind: 'faq', title: '', content: '', tagsText: '', status: 'approved' };
  constructor(private http: HttpClient, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.http.get<any[]>(`${API_V1_URL}/projects/`).subscribe(rows => { this.projects = rows || []; }); this.load(); }
  load(): void { this.error = ''; const query = this.projectId ? `?project_id=${this.projectId}` : ''; this.loadPolicy(query); this.http.get<any[]>(`${API_V1_URL}/governance/guidance${query}`).subscribe(rows => { this.guidance = rows || []; this.cdr.markForCheck(); }); this.http.get<any>(`${API_V1_URL}/governance/kpis${query}`).subscribe(row => { this.kpis = row; if (row.target) this.kpiTarget = {...row.target}; this.cdr.markForCheck(); }); }
  private loadPolicy(query: string): void { if (!this.canEdit) return; this.http.get<any>(`${API_V1_URL}/governance/operating-policy${query}`).subscribe(row => { this.policy = row || { timezone:'America/Lima',is_enabled:true,enforce_manual_messages:false,weekly_windows:{},blackout_dates:[] }; this.blackoutText = (this.policy.blackout_dates || []).join(', '); this.cdr.markForCheck(); }); }
  window(day: number): any { const values = this.policy.weekly_windows?.[String(day)] || []; return values[0] || {start:'09:00',end:'18:00'}; }
  active(day: number): boolean { return !!this.policy.weekly_windows?.[String(day)]?.length; }
  toggleDay(day: number): void { const windows = {...(this.policy.weekly_windows || {})}; if (this.active(day)) delete windows[String(day)]; else windows[String(day)] = [{start:'09:00',end:'18:00'}]; this.policy.weekly_windows = windows; }
  setTime(day: number, field: 'start'|'end', value: string): void { const windows = {...(this.policy.weekly_windows || {})}; windows[String(day)] = [{...this.window(day),[field]:value}]; this.policy.weekly_windows = windows; }
  savePolicy(): void { this.saving = true; const blackout_dates = this.blackoutText.split(',').map(value => value.trim()).filter(Boolean); this.http.put(`${API_V1_URL}/governance/operating-policy`, {...this.policy,blackout_dates,project_id:this.projectId || null}).subscribe({next:()=>this.done('Operating policy saved.'),error:e=>this.fail(e)}); }
  saveKpi(): void { this.saving = true; this.http.put(`${API_V1_URL}/governance/kpi-target`, {...this.kpiTarget,project_id:this.projectId || null}).subscribe({next:()=>{this.done('KPI targets saved.');this.load();},error:e=>this.fail(e)}); }
  addGuidance(): void { if (!this.draft.title.trim() || !this.draft.content.trim()) return; this.saving = true; this.http.post(`${API_V1_URL}/governance/guidance`, {project_id:this.projectId||null,kind:this.draft.kind,title:this.draft.title.trim(),content:this.draft.content.trim(),tags:this.draft.tagsText.split(',').map((x:string)=>x.trim()).filter(Boolean),status:this.draft.status}).subscribe({next:()=>{this.draft={kind:'faq',title:'',content:'',tagsText:'',status:'approved'};this.done('Guidance item added.');this.load();},error:e=>this.fail(e)}); }
  archive(item: any): void { this.http.delete(`${API_V1_URL}/governance/guidance/${item.id}`).subscribe(()=>this.load()); }
  private done(message:string):void{this.saving=false;this.success=message;this.error='';this.cdr.markForCheck();}
  private fail(error:any):void{this.saving=false;this.error=error.error?.detail?.message||error.error?.detail||'The settings could not be saved.';this.cdr.markForCheck();}
}
