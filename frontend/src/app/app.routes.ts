import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { roleGuard } from './core/guards/role.guard';
import { companyCompletionGuard } from './core/guards/company-completion.guard';

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
    path: 'activate-account',
    loadComponent: () =>
      import('./pages/activate-account/activate-account').then(
        (m) => m.ActivateAccountComponent
      ),
  },
  {
    path: 'set-password',
    loadComponent: () =>
      import('./pages/set-password/set-password').then(
        (m) => m.SetPasswordComponent
      ),
  },
  // 🚀 CORREGIDO: Ahora las rutas coinciden con los links de tu Landing Page
  {
    path: 'legal/privacy',
    loadComponent: () =>
      import('./pages/legal/privacy-policy/privacy-policy').then(
        (m) => m.PrivacyPolicyComponent
      ),
  },
  {
    path: 'legal/terms',
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
    canActivate: [authGuard, roleGuard],
    data: { roles: ['superadmin'] },
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
        path: 'integrations',
        loadComponent: () =>
          import('./features/admin-panel/integrations/integrations-page/integrations-page').then(
            (m) => m.IntegrationsPageComponent
          ),
      },
      {
        path: 'seo',
        loadComponent: () =>
          import('./features/admin-panel/seo/seo-page/seo-page').then((m) => m.SeoPageComponent),
      },
      {
        path: 'legal-compliance',
        loadComponent: () =>
          import(
            './features/admin-panel/legal-compliance/legal-compliance-page/legal-compliance-page'
          ).then((m) => m.LegalCompliancePageComponent),
      },
      {
        path: 'waitlist',
        loadComponent: () =>
          import(
            './features/admin-panel/waitlist/waitlist-page/waitlist-page'
          ).then((m) => m.WaitlistPageComponent),
      },
    ],
  },

  // ==========================================
  // 3. ZONA CLIENTES / TENANTS
  // ==========================================
  {
    path: 'app',
    canActivate: [authGuard],
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
        canActivate: [roleGuard, companyCompletionGuard],
        data: { roles: ['admin', 'assistant'] },
        loadComponent: () =>
          import('./pages/client/company/company-overview').then((m) => m.CompanyOverviewComponent),
      },
      {
        path: 'company/onboarding',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant'] },
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
        path: 'users',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant'] },
        loadComponent: () =>
          import('./pages/client/users/company-users').then((m) => m.CompanyUsersComponent),
      },
      {
        path: 'marketing',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant', 'mkt'] },
        loadComponent: () =>
          import('./pages/client/marketing/marketing').then((m) => m.MarketingComponent),
      },
      {
        path: 'leads',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant'] },
        loadComponent: () =>
          import('./pages/client/leads/leads').then((m) => m.LeadsComponent),
      },
      {
        path: 'schedule',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant', 'sales'] },
        loadComponent: () =>
          import('./pages/client/sales/sales').then((m) => m.SalesComponent),
      },
      { path: 'sales', redirectTo: 'schedule', pathMatch: 'full' },
      {
        path: 'agent',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant', 'mkt'] },
        loadComponent: () =>
          import('./pages/client/agent/agent').then((m) => m.AgentComponent),
      },
      {
        path: 'projects/:id/onboarding',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant'] },
        loadComponent: () =>
          import('./pages/client/projects/project-chat/project-chat').then(
            (m) => m.ProjectChatComponent
          ),
      },
      {
        path: 'projects/:id/marketing',
        canActivate: [roleGuard],
        data: { roles: ['admin', 'assistant', 'mkt'] },
        loadComponent: () =>
          import('./pages/client/marketing/marketing').then((m) => m.MarketingComponent),
      },
      {
        path: 'projects/:id/sales-report',
        loadComponent: () =>
          import('./pages/client/projects/project-sales-report/project-sales-report').then(
            (m) => m.ProjectSalesReportComponent
          ),
      },
      {
        path: 'projects/:id',
        loadComponent: () =>
          import('./pages/client/projects/project-overview/project-overview').then(
            (m) => m.ProjectOverviewComponent
          ),
      },
    ],
  },

  // Fallback
  { path: '**', redirectTo: '' },
];
