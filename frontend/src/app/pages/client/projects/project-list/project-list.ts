import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { ToastService } from '../../../../core/services/toast';
import { API_V1_URL } from '../../../../core/config/api.config';

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

  // FastAPI declares the collection route as "/". Keep the trailing slash so
  // GET and POST do not receive a 307 redirect from the backend.
  private readonly apiUrl = `${API_V1_URL}/projects/`;

  constructor(private http: HttpClient, private toastService: ToastService) {}

  ngOnInit(): void {
    this.loadProjects();
  }

  loadProjects() {
    this.isLoading = true;
    this.http.get<any[]>(this.apiUrl).subscribe({
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
    
    this.http.post<any>(this.apiUrl, this.newProject).subscribe({
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
