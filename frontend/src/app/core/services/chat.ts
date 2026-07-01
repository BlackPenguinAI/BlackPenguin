import { Injectable, isDevMode } from '@angular/core'; // 🚀 IMPORTANTE: Añadir isDevMode
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class ChatService {
  private apiUrl = isDevMode() 
    ? 'http://localhost:8000/api/v1/conversations' 
    : 'http://206.189.118.99:8000/api/v1/conversations';

  constructor(private http: HttpClient) {}

  analyzeDocument(file: File, prompt: string): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('prompt', prompt || 'Extrae los puntos clave.');
    
    return this.http.post(`${this.apiUrl}/analyze-pdf`, formData);
  }

  // 🚀 NUEVA FUNCIÓN: Permite charlar y mandar todo el historial
  sendMessage(messages: any[]): Observable<any> {
    return this.http.post(`${this.apiUrl}/chat-message`, { messages });
  }
}