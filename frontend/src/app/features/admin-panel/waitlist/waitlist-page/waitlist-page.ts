import { Component, OnInit, ChangeDetectorRef, isDevMode } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';

import { GlassCardComponent } from '../../../../shared/ui/glass-card/glass-card';
import { ButtonComponent } from '../../../../shared/ui/button/button';
import { ModalComponent } from '../../../../shared/ui/modal/modal';

@Component({
  selector: 'app-waitlist-page',
  standalone: true,
  imports: [CommonModule, GlassCardComponent, ButtonComponent, ModalComponent],
  providers: [DatePipe],
  templateUrl: './waitlist-page.html'
})
export class WaitlistPageComponent implements OnInit {
  entries: any[] = [];
  isLoading: boolean = true;
  
  showDeleteModal: boolean = false;
  entryToDeleteId: string | null = null;
  isDeleting: boolean = false;

  constructor(
    private http: HttpClient,
    private toast: ToastService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit() {
    this.loadWaitlist();
  }

  private get baseUrl() { return isDevMode() ? 'http://localhost:8000' : 'https://blackpenguin.ai'; }
  private get headers() {
    return new HttpHeaders().set('Authorization', `Bearer ${localStorage.getItem('bp_token')}`);
  }

  loadWaitlist() {
    this.isLoading = true;
    this.http.get<any[]>(`${this.baseUrl}/api/v1/waitlist/`, { headers: this.headers }).subscribe({
      next: (data) => {
        this.entries = data;
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.toast.showError('Failed to load waitlist.');
        this.isLoading = false;
        this.cdr.detectChanges();
      }
    });
  }

  openDeleteModal(id: string) {
    this.entryToDeleteId = id;
    this.showDeleteModal = true;
  }
  closeDeleteModal() {
    this.showDeleteModal = false;
    this.entryToDeleteId = null;
  }

  confirmDelete() {
    if (!this.entryToDeleteId) return;
    this.isDeleting = true;
    this.http.delete(`${this.baseUrl}/api/v1/waitlist/${this.entryToDeleteId}`, { headers: this.headers }).subscribe({
      next: () => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.loadWaitlist();
        this.toast.showSuccess('Entry deleted successfully.');
      },
      error: () => {
        this.isDeleting = false;
        this.closeDeleteModal();
        this.toast.showError('Failed to delete entry.');
      }
    });
  }
}