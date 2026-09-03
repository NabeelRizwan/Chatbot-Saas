import assert from "node:assert/strict";

import { defaultWidgetConfig, normalizeBot, toBackendBotCreate, toBackendBotUpdate } from "../lib/bot-utils.js";
import type { BotCreateInput } from "../types/bot.js";


const normalized = normalizeBot({
  id: 42,
  organization_id: 7,
  name: "Rich bot",
  description: "Description",
  category: "marketing",
  avatar_url: "https://example.test/avatar.png",
  status: "draft",
  provider: "claude",
  model_name: "claude-3-5-sonnet",
  ai_usage_mode: "byo",
  provider_api_key_masked: "sk-********cret",
  api_key: "cust********cret",
  system_prompt: "Business instructions",
  tone: "empathetic",
  capabilities: { web_search: true, file_analysis: false, temperature: 0.3 },
  welcome_message: "Welcome",
  widget_config: {
    primary_color: "#123456",
    position: "bottom-left",
    launcher_text: "Ask",
  },
  created_at: "2026-08-20T12:00:00",
});

assert.equal(normalized.organizationId, "7");
assert.equal(normalized.description, "Description");
assert.equal(normalized.category, "marketing");
assert.equal(normalized.avatarUrl, "https://example.test/avatar.png");
assert.equal(normalized.status, "draft");
assert.deepEqual([normalized.provider, normalized.model], ["claude", "claude-3-5-sonnet"]);
assert.equal(normalized.aiUsageMode, "byo");
assert.equal(normalized.providerApiKeyMasked, "sk-********cret");
assert.equal(normalized.systemPrompt, "Business instructions");
assert.equal(normalized.tone, "empathetic");
assert.deepEqual(normalized.capabilities, { web_search: true, file_analysis: false, temperature: 0.3 });
assert.equal(normalized.welcomeMessage, "Welcome");
assert.equal(normalized.widgetConfig.primary_color, "#123456");
assert.equal(normalized.widgetConfig.position, "bottom-left");
assert.equal(normalized.widgetConfig.placeholder_text, defaultWidgetConfig.placeholder_text);

const createInput: BotCreateInput = {
  organizationId: "7",
  name: "Rich bot",
  description: "Description",
  category: "sales",
  avatarUrl: "https://example.test/avatar.png",
  status: "active",
  provider: "grok",
  model: "grok-2",
  aiUsageMode: "byo",
  providerApiKey: "  sk-new-secret-value  ",
  systemPrompt: "System prompt",
  tone: "professional",
  capabilities: { web_search: false, file_analysis: true, temperature: 0.8 },
  welcomeMessage: "Hello",
  widgetConfig: { ...defaultWidgetConfig, launcher_icon: "bot" },
};
const createRequest = toBackendBotCreate(createInput);
assert.equal(createRequest.organization_id, 7);
assert.deepEqual([createRequest.provider, createRequest.model_name], ["grok", "grok-2"]);
assert.equal(createRequest.provider_api_key, "sk-new-secret-value");
assert.equal(createRequest.avatar_url, createInput.avatarUrl);
assert.deepEqual(createRequest.capabilities, createInput.capabilities);
assert.deepEqual(createRequest.widget_config, createInput.widgetConfig);

assert.throws(
  () => toBackendBotCreate({ ...createInput, organizationId: "" }),
  /Select a valid organization/,
);

const clearRequest = toBackendBotUpdate({ aiUsageMode: "platform" });
assert.equal(clearRequest.provider_api_key, null);

const preserveRequest = toBackendBotUpdate({ name: "Only this changed" });
assert.deepEqual(preserveRequest, { name: "Only this changed" });
assert.equal(Object.hasOwn(preserveRequest, "provider_api_key"), false);

const richUpdate = toBackendBotUpdate({
  description: null,
  status: "disabled",
  tone: "humorous",
  capabilities: { web_search: true, file_analysis: true, temperature: 1 },
  welcomeMessage: "Updated",
  widgetConfig: { ...defaultWidgetConfig, position: "bottom-left" },
});
assert.equal(richUpdate.description, null);
assert.equal(richUpdate.status, "disabled");
assert.equal(richUpdate.tone, "humorous");
assert.equal(richUpdate.widget_config?.position, "bottom-left");

console.log("Phase B frontend bot contract: 28 assertions passed");
