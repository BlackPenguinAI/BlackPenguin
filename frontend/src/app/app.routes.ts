import { Routes } from '@angular/router';
import { LandingComponent } from './pages/landing/landing';
import { LoginComponent } from './pages/login/login';
import { RegisterComponent } from './pages/register/register';

import { ChatComponent } from './pages/chat/chat';
import { Dashboard } from './pages/client/dashboard/dashboard';
import { ProfileComponent } from './pages/client/profile/profile';

import { StaffEmailsComponent } from './pages/staff/emails/emails';
import { StaffAiConfigComponent } from './pages/staff/ai-config/ai-config';
import { LayoutComponent } from './shared/layout/layout'; 

import { StaffDashboardComponent } from './pages/staff/dashboard/dashboard';
import { StaffProfileComponent } from './pages/staff/profile/profile';
import { StaffDevelopersComponent } from './pages/staff/developers/developers';

import { StaffPlansComponent } from './pages/staff/plans/plans';
import { SetPasswordComponent } from './pages/set-password/set-password';

import { StaffAiKeysComponent } from './pages/staff/ai-keys/ai-keys'; 
import { SmtpConfigComponent } from './pages/staff/smtp-config/smtp-config';

import { PrivacyPolicyComponent } from './pages/legal/privacy-policy/privacy-policy';
import { TermsConditionsComponent } from './pages/legal/terms-conditions/terms-conditions';

import { LegalEditorComponent } from './pages/admin/legal-editor/legal-editor';

import { ProjectListComponent } from './pages/client/projects/project-list/project-list';
import { ProjectChatComponent } from './pages/client/projects/project-chat/project-chat';

export const routes: Routes = [
  // 🌍 ZONAS LIBRES 
  { path: '', component: LandingComponent },
  { path: 'login', component: LoginComponent },
  { path: 'register', component: RegisterComponent },
  { path: 'set-password', component: SetPasswordComponent },

  // 📄 ZONA LEGAL (PÚBLICA)
  {
    path: 'legal',
    children: [
      { path: 'privacy', component: PrivacyPolicyComponent },
      { path: 'terms', component: TermsConditionsComponent }
    ]
  },

  // 🔒 ZONAS PROTEGIDAS (Envueltas en el Sidebar Layout)
  {
    path: '',
    component: LayoutComponent, 
    children: [
      // 1. Panel de Control Black Penguin
      {
        path: 'admin',
        children: [
          { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
          { path: 'dashboard', component: StaffDashboardComponent },
          { path: 'profile', component: StaffProfileComponent },
          { path: 'developers', component: StaffDevelopersComponent },
          { path: 'plans', component: StaffPlansComponent },
          { path: 'emails', component: StaffEmailsComponent },
          { path: 'ai-keys', component: StaffAiKeysComponent }, 
          { path: 'ai-config', component: StaffAiConfigComponent },
          { path: 'smtp-config', component: SmtpConfigComponent },
          { path: 'legal-editor', component: LegalEditorComponent } 
        ]
      },

      // 2. Panel de Clientes
      {
        path: 'app',
        children: [
          // 🚀 1. REDIRECCIÓN POR DEFECTO AL INICIAR SESIÓN
          { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
          
          // 🚀 2. NUEVAS RUTAS DEL OPERADOR (Tenant)
          // Nota: Deberás importar estos componentes arriba cuando los creemos
          { path: 'dashboard', component: Dashboard },
          { path: 'profile', component: ProfileComponent },
          
          // 🚀 3. EL CHAT DE ONBOARDING AHORA VIVE EN /company
          { path: 'company', component: ChatComponent },

          // 🚀 NUEVAS RUTAS DE PROYECTOS
          { path: 'projects', component: ProjectListComponent },
          { path: 'projects/:id/onboarding', component: ProjectChatComponent }
        ]
      }
    ]
  },
  
  // Rutas comodín
  { path: '**', redirectTo: '' }
];