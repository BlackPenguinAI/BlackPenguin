import { Routes } from '@angular/router';

export const routes: Routes = [
  // ==========================================
  // 1. ZONA PÚBLICA (Landing, Auth & Legales)
  // ==========================================
  {
    path: '',
    loadComponent: () =>
      import('./pages/landing/landing').then((m) => m.LandingComponent),
  },
  {
    path: 'login',
    loadComponent: () =>
      import('./pages/login/login').then((m) => m.LoginComponent),
  },
  {
    path: 'register',
    loadComponent: () =>
      import('./pages/register/register').then((m) => m.RegisterComponent),
  },
  {
    path: 'set-password',
    loadComponent: () =>
      import('./pages/set-password/set-password').then(
        (m) => m.SetPasswordComponent
      ),
  },
  {
    path: 'privacy-policy',
    loadComponent: () =>
      import('./pages/legal/privacy-policy/privacy-policy').then(
        (m) => m.PrivacyPolicyComponent
      ),
  },
  {
    path: 'terms-conditions',
    loadComponent: () =>
      import('./pages/legal/terms-conditions/terms-conditions').then(
        (m) => m.TermsConditionsComponent
      ),
  },

  // ==========================================
  // 2. ZONA SUPERADMIN / PANEL ADMIN (10 RUTAS)
  // ==========================================
  {
    path: 'admin',
    loadComponent: () =>
      import('./shared/layout/layout').then((m) => m.LayoutComponent),
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import(
            './features/admin-panel/dashboard/dashboard-page/dashboard-page'
          ).then((m) => m.DashboardPageComponent),
      },
      {
        path: 'profile',
        loadComponent: () =>
          import(
            './features/admin-panel/profile/profile-page/profile-page'
          ).then((m) => m.ProfilePageComponent),
      },
      {
        path: 'companies',
        loadComponent: () =>
          import(
            './features/admin-panel/companies/companies-page/companies-page'
          ).then((m) => m.CompaniesPageComponent),
      },
      {
        path: 'users',
        loadComponent: () =>
          import(
            './features/admin-panel/users/users-page/users-page'
          ).then((m) => m.UsersPageComponent),
      },
      {
        path: 'plans',
        loadComponent: () =>
          import(
            './features/admin-panel/plans/plans-page/plans-page'
          ).then((m) => m.PlansPageComponent),
      },
      // 🚀 RESTAURADAS: RUTAS DE IA
      {
        path: 'ai-infrastructure',
        loadComponent: () =>
          import(
            './features/admin-panel/ai-infrastructure/ai-infra-page/ai-infra-page'
          ).then((m) => m.AiInfraPageComponent),
      },
      {
        path: 'ai-settings',
        loadComponent: () =>
          import(
            './features/admin-panel/ai-settings/ai-settings-page/ai-settings-page'
          ).then((m) => m.AiSettingsPageComponent),
      },
      {
        path: 'email-settings',
        loadComponent: () =>
          import(
            './features/admin-panel/email-settings/email-settings-page/email-settings-page'
          ).then((m) => m.EmailSettingsPageComponent),
      },
      {
        path: 'messaging-settings',
        loadComponent: () =>
          import(
            './features/admin-panel/messaging-settings/messaging-settings-page/messaging-settings-page'
          ).then((m) => m.MessagingSettingsPageComponent),
      },
      {
        path: 'legal-compliance',
        loadComponent: () =>
          import(
            './features/admin-panel/legal-compliance/legal-compliance-page/legal-compliance-page'
          ).then((m) => m.LegalCompliancePageComponent),
      },
    ],
  },

  // ==========================================
  // 3. ZONA CLIENTES / TENANTS
  // ==========================================
  {
    path: 'app',
    loadComponent: () =>
      import('./shared/layout/layout').then((m) => m.LayoutComponent),
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./pages/client/dashboard/dashboard').then(
            (m) => m.Dashboard
          ),
      },
      {
        path: 'profile',
        loadComponent: () =>
          import('./pages/client/profile/profile').then(
            (m) => m.ProfileComponent
          ),
      },
      {
        path: 'company',
        loadComponent: () =>
          import('./pages/chat/chat').then((m) => m.ChatComponent),
      },
      {
        path: 'projects',
        loadComponent: () =>
          import('./pages/client/projects/project-list/project-list').then(
            (m) => m.ProjectListComponent
          ),
      },
      {
        path: 'projects/:id/onboarding',
        loadComponent: () =>
          import('./pages/client/projects/project-chat/project-chat').then(
            (m) => m.ProjectChatComponent
          ),
      },
    ],
  },

  // Fallback
  { path: '**', redirectTo: '' },
];