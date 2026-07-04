import { Injectable, isDevMode } from '@angular/core'; 
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class ChatService {
  // 🚀 URL DINÁMICA: Local vs Producción (Usando el dominio seguro)
  private apiUrl = isDevMode() 
    ? 'http://localhost:8000/api/v1/conversations' 
    : 'https://blackpenguin.ai/api/v1/conversations';

  constructor(private http: HttpClient) {}

  getHistory(sessionId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/history/${sessionId}`);
  }

  analyzeDocument(sessionId: string, file: File, prompt: string): Observable<any> {
    const formData = new FormData();
    formData.append('session_id', sessionId);
    formData.append('file', file);
    formData.append('prompt', prompt || 'Extrae los puntos clave.');
    
    return this.http.post(`${this.apiUrl}/analyze-pdf`, formData);
  }

  sendMessage(sessionId: string, messages: any[]): Observable<any> {
    return this.http.post(`${this.apiUrl}/chat-message`, { 
      session_id: sessionId, 
      messages: messages 
    });
  }
}