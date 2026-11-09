import { Component, importProvidersFrom } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TranslateModule } from '@ngx-translate/core';

// Same application-wide services as the shell, with HTTP kept entirely in memory.
// Individual suites retain their own higher-priority test providers and fixtures.
@Component({standalone:true,template:''})
class EmptyLoginRoute {}
export default [provideRouter([{path:'login',component:EmptyLoginRoute}]),importProvidersFrom(TranslateModule.forRoot()),
  provideHttpClient(),provideHttpClientTesting()];
