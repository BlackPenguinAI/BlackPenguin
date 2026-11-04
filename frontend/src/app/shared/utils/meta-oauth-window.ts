export interface MetaOAuthStart { authorization_url: string; expires_at: string; state: string; }
export interface MetaOAuthResult { status: 'connected' | 'error'; reason?: string; }

/** Auxiliary OAuth window; the opener never navigates or receives credentials. */
export class MetaOAuthWindow {
  private popup: Window | null = null;
  private state = '';
  private timer?: ReturnType<typeof setInterval>;
  private deadline = Date.now() + 10 * 60_000;
  private closed = false;
  private readonly receive = (event: MessageEvent) => {
    if (event.origin !== this.callbackOrigin || event.source !== this.popup || !this.state
        || event.data?.type !== 'bp-meta-oauth' || event.data.state !== this.state
        || (event.data.status !== 'connected' && event.data.status !== 'error')
        || (event.data.status === 'connected' && event.data.project_id !== this.projectId)) return;
    this.finish({status:event.data.status, reason:typeof event.data.reason === 'string' ? event.data.reason : ''});
  };
  constructor(private callbackOrigin: string, private projectId: string, private done: (result: MetaOAuthResult) => void) {}

  open(): boolean {
    this.popup = window.open('about:blank', '_blank', 'popup,width=650,height=760');
    if (!this.popup) return false;
    try {
      if (this.popup.document?.body) {
        this.popup.document.title = 'Connecting Meta';
        this.popup.document.body.textContent = 'Preparing secure Meta authorization… Your onboarding stays open in the original tab.';
      }
    } catch { /* The browser may already have separated the auxiliary window. */ }
    window.addEventListener('message', this.receive);
    this.timer = setInterval(() => {
      if (this.popup?.closed) this.finish({status:'error',reason:'The Meta window was closed. Refresh the saved account status or try again; your draft is unchanged.'});
      else if (Date.now() >= this.deadline) this.finish({status:'error',reason:'The Meta authorization attempt expired. Please try again; your draft is unchanged.'});
    }, 500);
    return true;
  }
  authorize(value: MetaOAuthStart): void {
    if (this.closed) return;
    const url = new URL(value.authorization_url);
    if (url.origin !== 'https://www.facebook.com' || !url.pathname.endsWith('/dialog/oauth')
        || !value.state || url.searchParams.get('state') !== value.state) throw new Error('Invalid Meta authorization URL.');
    this.state = value.state;
    const expires = Date.parse(value.expires_at);
    this.deadline = Number.isFinite(expires) ? Math.min(expires, Date.now() + 10 * 60_000) : this.deadline;
    if (this.popup && !this.popup.closed) this.popup.location.replace(url.toString());
  }
  private finish(result: MetaOAuthResult): void {
    if (this.closed) return;
    this.dispose(); this.done(result);
  }
  dispose(): void {
    this.closed = true;
    if (this.timer) clearInterval(this.timer);
    window.removeEventListener('message', this.receive);
    try { this.popup?.close(); } catch { /* A separated browser window can be closed manually. */ }
  }
}
