import { Component, OnInit, isDevMode } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';

@Component({
  selector: 'app-project-list',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './project-list.html',
  styleUrls: ['./project-list.scss']
})
export class ProjectListComponent implements OnInit {
  projects: any[] = [];
  isLoading: boolean = true;
  showModal: boolean = false;
  isCreating: boolean = false;

  newProject = { name: '', address: '', city: '' };

  private apiUrl = isDevMode() ? 'http://localhost:8000/api/v1/properties' : 'https://blackpenguin.ai/api/v1/properties';

  constructor(private http: HttpClient, private toastService: ToastService) {}

  ngOnInit(): void {
    this.loadProjects();
  }

  private getHeaders() {
    return { headers: new HttpHeaders({ 'Authorization': `Bearer ${localStorage.getItem('bp_token')}` }) };
  }

  loadProjects() {
    this.isLoading = true;
    this.http.get<any[]>(this.apiUrl, this.getHeaders()).subscribe({
      next: (data) => {
        this.projects = data;
        this.isLoading = false;
      },
      error: () => {
        this.toastService.showError('Error loading projects');
        this.isLoading = false;
      }
    });
  }

  createProject() {
    if (!this.newProject.name) return;
    this.isCreating = true;
    
    this.http.post<any>(this.apiUrl, this.newProject, this.getHeaders()).subscribe({
      next: (created) => {
        this.projects.push(created);
        this.toastService.showSuccess('Project created successfully');
        this.closeModal();
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
}