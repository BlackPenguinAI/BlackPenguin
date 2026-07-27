import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './profile.html',
  styleUrls: ['./profile.scss']
})
export class ProfileComponent implements OnInit {
  userEmail: string = '';

  constructor() {}

  ngOnInit(): void {
    // 🚀 Extraemos el email del token de forma sencilla
    const token = localStorage.getItem('token');
    if (token) {
      try {
        const payloadBase64 = token.split('.')[1];
        const decodedJson = atob(payloadBase64);
        const decodedPayload = JSON.parse(decodedJson);
        this.userEmail = decodedPayload.sub || 'admin@company.com';
      } catch (error) {
        console.error('Error decoding token', error);
      }
    }
  }
}