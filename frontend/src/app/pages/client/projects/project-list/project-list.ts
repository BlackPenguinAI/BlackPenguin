import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { finalize } from 'rxjs';
import { ToastService } from '../../../../core/services/toast';
import { API_V1_URL } from '../../../../core/config/api.config';

interface ProjectDeletionImpact {
  can_delete: boolean;
  leads: number;
  meetings: number;
  campaigns: number;
  active_campaigns: number;
  brokers: number;
  sources: number;
  files: number;
  recommended_action: 'delete' | 'archive';
}

@Component({
  selector: 'app-project-list',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './project-list.html',
  styleUrls: ['./project-list.scss']
})
export class ProjectListComponent implements OnInit, OnDestroy {
  projects: any[] = [];
  isLoading: boolean = true;
  showModal: boolean = false;
  isCreating: boolean = false;
  showDeleteModal = false;
  isCheckingDeletion = false;
  isDeleting = false;
  projectToDelete: any | null = null;
  deletionImpact: ProjectDeletionImpact | null = null;
  confirmProjectName = '';
  readonly canManageProjects = localStorage.getItem('bp_role') === 'admin';
  private destroyed = false;

  newProject = { name: '', address: '', city: '' };

  // FastAPI declares the collection route as "/". Keep the trailing slash so
  // GET and POST do not receive a 307 redirect from the backend.
  private readonly apiUrl = `${API_V1_URL}/projects/`;

  constructor(
    private http: HttpClient,
    private toastService: ToastService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.loadProjects();
  }

  ngOnDestroy(): void { this.destroyed = true; }

  loadProjects() {
    this.isLoading = true;
    this.http.get<any[]>(this.apiUrl).pipe(
      finalize(() => {
        this.isLoading = false;
        if (!this.destroyed) this.cdr.detectChanges();
      }),
    ).subscribe({
      next: (data) => {
        this.projects = [...data];
      },
      error: () => {
        this.toastService.showError('Error loading projects');
      }
    });
  }

  createProject() {
    if (!this.newProject.name) return;
    this.isCreating = true;
    
    this.http.post<any>(this.apiUrl, this.newProject).subscribe({
      next: (created) => {
        this.projects = [created, ...this.projects];
        this.toastService.showSuccess('Project created successfully');
        this.closeModal();
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.toastService.showError(err.error?.detail || 'Error creating project');
        this.isCreating = false;
      }
    });
  }

  openModal() { this.showModal = true; }
  closeModal() {
    this.showModal = false;
    this.isCreating = false;
    this.newProject = { name: '', address: '', city: '' };
  }

  openDeleteModal(project: any): void {
    this.projectToDelete = project;
    this.deletionImpact = null;
    this.confirmProjectName = '';
    this.showDeleteModal = true;
    this.isCheckingDeletion = true;
    this.http.get<ProjectDeletionImpact>(`${API_V1_URL}/projects/${project.id}/deletion-impact`).pipe(
      finalize(() => {
        this.isCheckingDeletion = false;
        if (!this.destroyed) this.cdr.detectChanges();
      }),
    ).subscribe({
      next: (impact) => this.deletionImpact = impact,
      error: () => {
        this.toastService.showError('Could not check whether this project can be deleted');
        this.closeDeleteModal();
      },
    });
  }

  closeDeleteModal(): void {
    this.showDeleteModal = false;
    this.projectToDelete = null;
    this.deletionImpact = null;
    this.confirmProjectName = '';
  }

  deleteProject(): void {
    const project = this.projectToDelete;
    if (!project || !this.deletionImpact?.can_delete || this.confirmProjectName !== project.name) return;
    this.isDeleting = true;
    this.http.delete(`${API_V1_URL}/projects/${project.id}`, {
      body: { confirm_name: this.confirmProjectName },
    }).pipe(
      finalize(() => {
        this.isDeleting = false;
        if (!this.destroyed) this.cdr.detectChanges();
      }),
    ).subscribe({
      next: () => {
        this.projects = this.projects.filter((item) => item.id !== project.id);
        this.toastService.showSuccess('Project deleted permanently');
        this.closeDeleteModal();
      },
      error: (error) => this.toastService.showError(
        error.error?.detail?.message || error.error?.detail || 'Error deleting project',
      ),
    });
  }

  archiveProject(): void {
    const project = this.projectToDelete;
    if (!project) return;
    this.isDeleting = true;
    this.http.post(`${API_V1_URL}/projects/${project.id}/archive`, {}).pipe(
      finalize(() => {
        this.isDeleting = false;
        if (!this.destroyed) this.cdr.detectChanges();
      }),
    ).subscribe({
      next: () => {
        this.projects = this.projects.filter((item) => item.id !== project.id);
        this.toastService.showSuccess('Project archived');
        this.closeDeleteModal();
      },
      error: () => this.toastService.showError('Error archiving project'),
    });
  }
}
