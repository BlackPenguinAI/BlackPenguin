import { ComponentFixture, TestBed } from "@angular/core/testing";
import {
  HttpClientTestingModule,
  HttpTestingController,
} from "@angular/common/http/testing";
import { TranslateModule } from "@ngx-translate/core";

import { ChatComponent } from "./chat";
import { EMPTY_COMPANY_PROFILE } from "./company-onboarding.models";

describe("ChatComponent", () => {
  let component: ChatComponent;
  let fixture: ComponentFixture<ChatComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        ChatComponent,
        HttpClientTestingModule,
        TranslateModule.forRoot(),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ChatComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it("should create", () => {
    expect(component).toBeTruthy();
  });

  it("should expose required and conditional fields separately", () => {
    component.profile = {
      ...EMPTY_COMPANY_PROFILE,
      fields: [
        {
          key: "official_company_name",
          label: "Official company name",
          requirement: "required",
          status: "confirmed",
          applicable: null,
        },
        {
          key: "dba",
          label: "DBA",
          requirement: "conditionally_required",
          status: "not_applicable",
          applicable: false,
        },
      ],
    };

    expect(component.requiredFields.map((field) => field.key)).toEqual([
      "official_company_name",
    ]);
    expect(component.conditionalFields.map((field) => field.key)).toEqual([
      "dba",
    ]);
  });

  it("should use distinct icons for confirmed, pending and conflicting fields", () => {
    expect(component.statusIcon("confirmed")).toBe("check_circle");
    expect(component.statusIcon("pending_confirmation")).toBe("schedule");
    expect(component.statusIcon("conflicting")).toBe("error");
  });

  it("should expose onboarding status labels in English", () => {
    expect(component.statusLabel("missing")).toBe("Missing");
    expect(component.statusLabel("pending_confirmation")).toBe(
      "Pending confirmation",
    );
    expect(component.statusLabel("not_applicable")).toBe("Not applicable");
  });

  it("should not expose the removed session initializer", () => {
    expect(
      (component as unknown as { initSession?: unknown }).initSession,
    ).toBeUndefined();
  });

  it("should render Markdown and remove unsafe HTML attributes", () => {
    const html = component.renderMarkdown(
      '**Confirmed** <img src="x" onerror="alert(1)">',
    );

    expect(html).toContain("<strong>Confirmed</strong>");
    expect(html).not.toContain("onerror");
  });

  it("should initialize the assistant when chat history is empty", () => {
    const initializeSpy = vi
      .spyOn(component, "initializeChat")
      .mockImplementation(() => undefined);

    component.loadChatHistory();
    httpMock
      .expectOne((request) =>
        request.url.endsWith("/api/v1/company-onboarding/chat"),
      )
      .flush([]);

    expect(initializeSpy).toHaveBeenCalledOnce();
  });
});
