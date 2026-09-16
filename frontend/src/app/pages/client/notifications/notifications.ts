import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { API_V1_URL } from '../../../core/config/api.config';

@Component({ selector: 'app-notifications', standalone: true, imports: [CommonModule, FormsModule], templateUrl: './notifications.html', styleUrl: './notifications.scss' })
export class NotificationsComponent implements OnInit, OnDestroy {
  items: any[] = []; loading = true; unreadOnly = false; private timer?: ReturnType<typeof setInterval>;
  constructor(private http: HttpClient, private router: Router, private cdr: ChangeDetectorRef) {}
  ngOnInit(): void { this.load(); this.timer = setInterval(() => this.load(false), 15000); }
  ngOnDestroy(): void { if (this.timer) clearInterval(this.timer); }
  load(showLoading = true): void { if (showLoading) this.loading = true; this.http.get<any[]>(`${API_V1_URL}/governance/notifications?unread_only=${this.unreadOnly}`).subscribe(rows => { this.items = rows || []; this.loading = false; this.cdr.markForCheck(); }); }
  open(item: any): void { const done = () => { if (item.action_url) void this.router.navigateByUrl(item.action_url); else this.load(false); }; if (item.read_at) done(); else this.http.post(`${API_V1_URL}/governance/notifications/${item.id}/read`, {}).subscribe(() => done()); }
}
