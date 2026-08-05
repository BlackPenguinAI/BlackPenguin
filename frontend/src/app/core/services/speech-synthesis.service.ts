import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export type SpeechSynthesisState = 'idle' | 'playing' | 'paused' | 'error';

@Injectable({ providedIn: 'root' })
export class SpeechSynthesisService {
  private readonly stateSubject = new BehaviorSubject<SpeechSynthesisState>('idle');
  private readonly messageSubject = new BehaviorSubject<string | null>(null);
  readonly state$ = this.stateSubject.asObservable();
  readonly activeMessageId$ = this.messageSubject.asObservable();
  readonly isSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;

  play(messageId: string, text: string, language: string): void {
    if (!this.isSupported || !text.trim()) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(this.clean(text));
    utterance.lang = language;
    const voices = window.speechSynthesis.getVoices();
    utterance.voice = voices.find((voice) => voice.lang.toLowerCase() === language.toLowerCase())
      || voices.find((voice) => voice.lang.toLowerCase().startsWith(language.slice(0, 2).toLowerCase()))
      || null;
    utterance.onstart = () => { this.messageSubject.next(messageId); this.stateSubject.next('playing'); };
    utterance.onend = () => this.reset();
    utterance.onerror = () => { this.messageSubject.next(messageId); this.stateSubject.next('error'); };
    window.speechSynthesis.speak(utterance);
  }

  pause(): void { if (this.isSupported) { window.speechSynthesis.pause(); this.stateSubject.next('paused'); } }
  resume(): void { if (this.isSupported) { window.speechSynthesis.resume(); this.stateSubject.next('playing'); } }
  stop(): void { if (this.isSupported) window.speechSynthesis.cancel(); this.reset(); }

  private reset(): void { this.messageSubject.next(null); this.stateSubject.next('idle'); }
  private clean(value: string): string {
    return value
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/!\[[^\]]*]\([^)]*\)/g, ' ')
      .replace(/\[([^\]]+)]\([^)]*\)/g, '$1')
      .replace(/[*_#>`~|-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
}
