import { Injectable, NgZone } from '@angular/core';
import { BehaviorSubject, Subject } from 'rxjs';


export type SpeechRecognitionState = 'idle' | 'listening' | 'error';

export interface SpeechTranscript {
  finalText: string;
  interimText: string;
}

interface BrowserSpeechRecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}

interface BrowserSpeechRecognitionEvent {
  results: { length: number; [index: number]: BrowserSpeechRecognitionResult };
}

interface BrowserSpeechRecognitionErrorEvent {
  error: string;
}

interface BrowserSpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;


@Injectable({ providedIn: 'root' })
export class SpeechRecognitionService {
  private recognition: BrowserSpeechRecognition | null = null;
  private readonly stateSubject = new BehaviorSubject<SpeechRecognitionState>('idle');
  private readonly transcriptSubject = new Subject<SpeechTranscript>();
  private readonly errorSubject = new Subject<string>();

  readonly state$ = this.stateSubject.asObservable();
  readonly transcript$ = this.transcriptSubject.asObservable();
  readonly error$ = this.errorSubject.asObservable();

  constructor(private readonly zone: NgZone) {}

  get isSupported(): boolean {
    return !!this.constructorForBrowser();
  }

  start(language: string): void {
    const Constructor = this.constructorForBrowser();
    if (!Constructor) {
      this.errorSubject.next('Speech recognition is not supported by this browser.');
      return;
    }
    this.abort();
    const recognition = new Constructor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = language;
    recognition.onresult = (event) => this.zone.run(() => {
      let finalText = '';
      let interimText = '';
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0]?.transcript || '';
        if (result.isFinal) finalText += transcript;
        else interimText += transcript;
      }
      this.transcriptSubject.next({ finalText: finalText.trim(), interimText: interimText.trim() });
    });
    recognition.onerror = (event) => this.zone.run(() => {
      this.stateSubject.next('error');
      this.errorSubject.next(this.messageForError(event.error));
    });
    recognition.onend = () => this.zone.run(() => {
      this.recognition = null;
      if (this.stateSubject.value !== 'error') this.stateSubject.next('idle');
    });
    this.recognition = recognition;
    try {
      recognition.start();
      this.stateSubject.next('listening');
    } catch {
      this.recognition = null;
      this.stateSubject.next('error');
      this.errorSubject.next('The microphone could not be started.');
    }
  }

  stop(): void {
    this.recognition?.stop();
  }

  abort(): void {
    const active = this.recognition;
    this.recognition = null;
    active?.abort();
    this.stateSubject.next('idle');
  }

  private constructorForBrowser(): BrowserSpeechRecognitionConstructor | null {
    if (typeof window === 'undefined') return null;
    const browserWindow = window as typeof window & {
      SpeechRecognition?: BrowserSpeechRecognitionConstructor;
      webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
    };
    return browserWindow.SpeechRecognition || browserWindow.webkitSpeechRecognition || null;
  }

  private messageForError(error: string): string {
    if (error === 'not-allowed' || error === 'service-not-allowed') return 'Microphone permission was denied.';
    if (error === 'no-speech') return 'No speech was detected. Try again when you are ready.';
    if (error === 'audio-capture') return 'No available microphone was found.';
    return 'Speech recognition stopped unexpectedly.';
  }
}
