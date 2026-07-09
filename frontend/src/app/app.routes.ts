import { Routes } from '@angular/router';
import { LandingComponent } from './pages/landing/landing';
import { LoginComponent } from './pages/login/login';
import { RegisterComponent } from './pages/register/register';
import { ChatComponent } from './pages/chat/chat'; 
import { StaffEmailsComponent } from './pages/staff/emails/emails';
import { StaffAiConfigComponent } from './pages/staff/ai-config/ai-config';
import { LayoutComponent } from './shared/layout/layout'; // 🚀 Importamos el Layout

import { StaffDashboardComponent } from './pages/staff/dashboard/dashboard';
import { StaffProfileComponent } from './pages/staff/profile/profile';
import { StaffDevelopersComponent } from './pages/staff/developers/developers';

export const routes: Routes = [
  // 🌍 ZONAS LIBRES (No tienen Menú Lateral)
  { path: '', component: LandingComponent },
  { path: 'login', component: LoginComponent },
  { path: 'register', component: RegisterComponent },

  // 🛡️ ZONAS PROTEGIDAS (Envueltas en el Sidebar Layout)
  {
    path: '',
    component: LayoutComponent, // 🚀 El componente maestro envuelve todo esto
    children: [
      
      // 1. Panel de Control Black Penguin
      {
        path: 'admin',
        children: [
          { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
          { path: 'dashboard', component: StaffDashboardComponent },
          { path: 'profile', component: StaffProfileComponent },
          { path: 'developers', component: StaffDevelopersComponent },
          { path: 'emails', component: StaffEmailsComponent },
          { path: 'ai-config', component: StaffAiConfigComponent },
        ]
      },

      // 2. Panel de Clientes
      {
        path: 'app',
        children: [
          { path: '', redirectTo: 'chat', pathMatch: 'full' },
          { path: 'chat', component: ChatComponent },
          // Los demás módulos los irás agregando aquí...
        ]
      }

    ]
  },

  // 🔄 Redirección por defecto
  { path: '**', redirectTo: '' }
];