import React, { useEffect, useState } from "react";
import {
  type BackendKind,
  type SummarizerSettingsPut,
  type TestConnectionRequest,
  fetchSummarizerSettings,
  putSummarizerSettings,
  testSummarizerConnection,
} from "../api";

type SaveState = "idle" | "saving" | "saved" | "error";
type TestState = "idle" | "testing" | "ok" | "fail";

type FormState = {
  backend: BackendKind;
  base_url: string;
  api_key: string;
  model: string;
};

const OPENAI_DEFAULTS: Partial<FormState> = {
  base_url: "http://192.168.2.104:52624/v1",
  api_key: "lm",
  model: "gemma-4-31b-it@q6_k",
};

const CLAUDE_DEFAULTS: Partial<FormState> = {
  base_url: "",
  api_key: "",
  model: "claude-haiku-4-5-20251001",
};

export default function SettingsPage(): React.ReactElement {
  const [form, setForm] = useState<FormState>({
    backend: "openai_compat",
    base_url: OPENAI_DEFAULTS.base_url!,
    api_key: "",
    model: OPENAI_DEFAULTS.model!,
  });
  const [apiKeyPlaceholder, setApiKeyPlaceholder] = useState("(unchanged)");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState("");
  const [testState, setTestState] = useState<TestState>("idle");
  const [testResult, setTestResult] = useState<{ latency_ms: number; error?: string } | null>(
    null,
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // useEffect with empty deps: runs once on mount to load persisted settings
    fetchSummarizerSettings()
      .then((s) => {
        setForm({
          backend: s.backend,
          base_url: s.base_url,
          api_key: "",
          model: s.model,
        });
        setApiKeyPlaceholder(s.api_key_masked || "(none)");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []); // analyze-ignore: empty-deps

  const handleBackendChange = (e: React.ChangeEvent<HTMLSelectElement>): void => {
    const next = e.target.value as BackendKind;
    const defaults = next === "claude" ? CLAUDE_DEFAULTS : OPENAI_DEFAULTS;
    setForm((prev) => ({
      ...prev,
      backend: next,
      base_url: defaults.base_url ?? prev.base_url,
      api_key: "",
      model: defaults.model ?? prev.model,
    }));
    setTestState("idle");
    setTestResult(null);
  };

  const handleField =
    (field: keyof Omit<FormState, "backend">) =>
    (e: React.ChangeEvent<HTMLInputElement>): void => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
      setTestState("idle");
      setTestResult(null);
    };

  const handleSave = async (): Promise<void> => {
    setSaveState("saving");
    setSaveError("");
    const body: SummarizerSettingsPut = {
      backend: form.backend,
      base_url: form.base_url,
      model: form.model,
    };
    if (form.api_key !== "") body.api_key = form.api_key;

    try {
      const updated = await putSummarizerSettings(body);
      setApiKeyPlaceholder(updated.api_key_masked || "(none)");
      setForm((prev) => ({ ...prev, api_key: "" }));
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 2500);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
      setSaveState("error");
    }
  };

  const handleTest = async (): Promise<void> => {
    setTestState("testing");
    setTestResult(null);
    const req: TestConnectionRequest = {
      backend: form.backend,
      base_url: form.base_url,
      api_key: form.api_key || apiKeyPlaceholder,
      model: form.model,
    };
    try {
      const result = await testSummarizerConnection(req);
      setTestState(result.ok ? "ok" : "fail");
      setTestResult({ latency_ms: result.latency_ms, error: result.error });
    } catch (err) {
      setTestState("fail");
      setTestResult({ latency_ms: 0, error: err instanceof Error ? err.message : String(err) });
    }
  };

  if (loading) return <div className="settings-page">Loading…</div>;

  return (
    <div className="settings-page">
      <h2>設定</h2>

      <section className="settings-section">
        <h3>要約バックエンド</h3>

        <div className="settings-field">
          <label htmlFor="backend">バックエンド種別</label>
          <select id="backend" value={form.backend} onChange={handleBackendChange}>
            <option value="openai_compat">OpenAI 互換（LM Studio / Ollama / vLLM）</option>
            <option value="claude">Claude API（Anthropic）</option>
          </select>
        </div>

        {form.backend === "openai_compat" && (
          <div className="settings-field">
            <label htmlFor="base_url">Base URL</label>
            <input
              id="base_url"
              type="text"
              value={form.base_url}
              onChange={handleField("base_url")}
              placeholder="http://localhost:11434/v1"
            />
          </div>
        )}

        <div className="settings-field">
          <label htmlFor="model">モデル</label>
          <input
            id="model"
            type="text"
            value={form.model}
            onChange={handleField("model")}
            placeholder={form.backend === "claude" ? "claude-haiku-4-5-20251001" : "model-name"}
          />
        </div>

        <div className="settings-field">
          <label htmlFor="api_key">
            {form.backend === "claude" ? "Anthropic API キー" : "API キー"}
          </label>
          <input
            id="api_key"
            type="password"
            value={form.api_key}
            onChange={handleField("api_key")}
            placeholder={apiKeyPlaceholder}
            autoComplete="new-password"
          />
          <span className="settings-hint">空欄のまま保存すると現在のキーを保持します</span>
        </div>

        <div className="settings-actions">
          <button
            className="btn-test"
            onClick={() => void handleTest()}
            disabled={testState === "testing"}
          >
            {testState === "testing" ? "接続テスト中…" : "接続テスト"}
          </button>

          <button
            className="btn-save"
            onClick={() => void handleSave()}
            disabled={saveState === "saving"}
          >
            {saveState === "saving" ? "保存中…" : "保存"}
          </button>
        </div>

        {testResult !== null && (
          <div className={`settings-test-result ${testState === "ok" ? "ok" : "fail"}`}>
            {testState === "ok" ? (
              <span>✓ 接続成功 — {testResult.latency_ms} ms</span>
            ) : (
              <span>✗ 接続失敗: {testResult.error}</span>
            )}
          </div>
        )}

        {saveState === "saved" && <div className="settings-save-ok">保存しました</div>}
        {saveState === "error" && <div className="settings-save-error">{saveError}</div>}
      </section>
    </div>
  );
}
