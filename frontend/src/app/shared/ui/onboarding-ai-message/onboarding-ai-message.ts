import { CommonModule } from '@angular/common';
import { ChangeDetectorRef, Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { marked } from 'marked';
import { Subscription } from 'rxjs';

import { SpeechSynthesisService, SpeechSynthesisState } from '../../../core/services/speech-synthesis.service';
import { OnboardingQuestion, OnboardingResponseOptionsComponent } from '../onboarding-response-options/onboarding-response-options';

export interface StructuredAiMessage {
  id?: string;
  content: string;
  created_at: string | Date;
  ui_payload?: OnboardingQuestion | null;
  response_payload?: { status: string; answer: string; selected_option?: string | null; custom?: boolean } | null;
}

@Component({
  selector: 'app-onboarding-ai-message', standalone: true,
  imports: [CommonModule, OnboardingResponseOptionsComponent],
  templateUrl: './onboarding-ai-message.html', styleUrl: './onboarding-ai-message.scss',
})
export class OnboardingAiMessageComponent implements OnInit, OnDestroy {
  @Input({ required: true }) message!: StructuredAiMessage;
  @Input() active = false;
  @Input() disabled = false;
  @Output() selected = new EventEmitter<string>();
  @Output() custom = new EventEmitter<void>();
  speechState: SpeechSynthesisState = 'idle';
  activeMessageId: string | null = null;
  private readonly subscriptions = new Subscription();

  constructor(readonly speech: SpeechSynthesisService, private readonly cdr: ChangeDetectorRef) {}
  ngOnInit(): void {
    this.subscriptions.add(this.speech.state$.subscribe((state) => { this.speechState = state; this.cdr.detectChanges(); }));
    this.subscriptions.add(this.speech.activeMessageId$.subscribe((id) => { this.activeMessageId = id; this.cdr.detectChanges(); }));
  }
  ngOnDestroy(): void { this.subscriptions.unsubscribe(); }
  get messageId(): string { return this.message.id || `transient-${String(this.message.created_at)}`; }
  get isSpeaking(): boolean { return this.activeMessageId === this.messageId; }
  get choicesText(): string {
    const question = this.message.ui_payload;
    const choices = question ? (question.options.length ? question.options : question.examples) : [];
    return choices.length ? ` Suggested responses: ${choices.join(', ')}.` : '';
  }
  renderMarkdown(content: string): string { return marked.parse(content, { async: false, breaks: true }) as string; }
  toggleSpeech(): void {
    if (!this.isSpeaking) {
      const language = (localStorage.getItem('bp_lang') || 'en') === 'es' ? 'es-PE' : 'en-US';
      this.speech.play(this.messageId, this.message.content + this.choicesText, language);
    } else if (this.speechState === 'paused') this.speech.resume();
    else this.speech.pause();
  }
  stopSpeech(): void { this.speech.stop(); }
}
