/**
 * SettingsPanel — gear-icon button + slide-over modal for picking
 * the LLM model and embedding model at runtime (no server restart needed).
 */

import { useEffect, useRef, useState } from 'react'
import {
  EMBEDDING_OPTIONS,
  fetchModels,
  fetchProviders,
  fetchSettings,
  saveSettings,
  type AppSettings,
  type ProviderInfo,
} from './services/settingsService'
import { config } from './config'

// ── Gear icon SVG ─────────────────────────────────────────────────────────────

function GearIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function SettingsPanel() {
  const [open, setOpen] = useState(false)
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [draft, setDraft] = useState<{ llm_provider: string; llm_model: string; embedding_model: string } | null>(null)
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [models, setModels] = useState<string[]>([])
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [customModel, setCustomModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null)
  const modalRef = useRef<HTMLDivElement>(null)

  // Load current settings whenever the panel opens
  useEffect(() => {
    if (!open) return
    setFeedback(null)
    fetchSettings()
      .then((s) => {
        setSettings(s)
        setDraft({ llm_provider: s.llm_provider, llm_model: s.llm_model, embedding_model: s.embedding_model })
        setCustomModel('')
      })
      .catch(() => setFeedback({ ok: false, text: 'Could not load current settings.' }))
    fetchProviders()
      .then(setProviders)
      .catch(() => setProviders([]))
  }, [open])

  // Live model catalog for the chosen provider
  const draftProvider = draft?.llm_provider
  const isPreset = providers.some((p) => p.id === draftProvider)
  useEffect(() => {
    setModels([])
    setModelsError(null)
    if (!open || !draftProvider || !isPreset) return
    fetchModels(draftProvider)
      .then(setModels)
      .catch((e) => setModelsError(e instanceof Error ? e.message : 'Could not load models'))
  }, [open, draftProvider, isPreset])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  if (config.useMockApi) return null // settings require live backend

  async function handleSave() {
    if (!draft) return
    setSaving(true)
    setFeedback(null)
    const effectiveModel = customModel.trim() || draft.llm_model
    try {
      const providerChanged = settings !== null && draft.llm_provider !== settings.llm_provider
      const updated = await saveSettings({
        ...(providerChanged ? { llm_provider: draft.llm_provider } : {}),
        llm_model: effectiveModel,
        embedding_model: draft.embedding_model,
      })
      setSettings(updated)
      setDraft({ llm_provider: updated.llm_provider, llm_model: updated.llm_model, embedding_model: updated.embedding_model })
      setCustomModel('')
      setFeedback({ ok: true, text: `Saved — all pipelines now use ${updated.llm_provider} / ${updated.llm_model}` })
    } catch (e) {
      setFeedback({ ok: false, text: e instanceof Error ? e.message : 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  const currentModel = draft?.llm_model ?? ''
  const isCustom = models.length > 0 && !models.includes(currentModel)

  return (
    <>
      {/* Trigger button */}
      <button
        id="settings-btn"
        type="button"
        className="theme-toggle"
        onClick={() => setOpen(true)}
        aria-label="Open settings"
        title="Settings — model & embedding"
      >
        <GearIcon />
      </button>

      {/* Modal overlay */}
      {open && (
        <div
          className="settings-backdrop"
          role="presentation"
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false) }}
        >
          <div
            id="settings-panel"
            className="settings-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            ref={modalRef}
          >
            {/* Header */}
            <div className="settings-head">
              <h2 id="settings-title" className="settings-title">
                <GearIcon /> Settings
              </h2>
              <button
                type="button"
                className="settings-close"
                onClick={() => setOpen(false)}
                aria-label="Close settings"
              >
                ✕
              </button>
            </div>

            {!settings && !feedback && (
              <p className="settings-loading muted">Loading current configuration…</p>
            )}

            {feedback && (
              <p className={feedback.ok ? 'flash' : 'error-box pad'} role="status">
                {feedback.text}
              </p>
            )}

            {settings && draft && (
              <>
                {/* Provider selector — applies to all three pipelines */}
                <div className="settings-field">
                  <label htmlFor="llm-provider" className="label">Provider</label>
                  <select
                    id="llm-provider"
                    value={draft.llm_provider}
                    onChange={(e) => {
                      const next = e.target.value
                      setDraft((d) => d && { ...d, llm_provider: next, llm_model: next === settings.llm_provider ? settings.llm_model : '' })
                      setCustomModel('')
                    }}
                  >
                    {!providers.some((p) => p.id === settings.llm_provider) && (
                      <option value={settings.llm_provider}>{settings.llm_provider} (server default)</option>
                    )}
                    {providers.map((p) => (
                      <option key={p.id} value={p.id} disabled={!p.configured}>
                        {p.label}{p.configured ? '' : ' — API key not set'}
                      </option>
                    ))}
                  </select>
                </div>

                {/* LLM model selector */}
                <fieldset className="settings-fieldset">
                  <legend className="label">Intelligent Engine · Model</legend>
                  {models.length > 0 ? (
                    <div className="settings-model-grid">
                      {models.map((m) => (
                        <label
                          key={m}
                          className={`settings-model-card ${draft.llm_model === m && !customModel ? 'selected' : ''}`}
                        >
                          <input
                            type="radio"
                            name="llm_model"
                            value={m}
                            checked={draft.llm_model === m && !customModel}
                            onChange={() => { setDraft((d) => d && { ...d, llm_model: m }); setCustomModel('') }}
                          />
                          <span className="settings-model-name">{m}</span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <p className="muted small">
                      {modelsError ?? (isPreset ? 'Loading models…' : 'No model list for this provider — enter a model ID.')}
                    </p>
                  )}
                  <div className="settings-custom-row">
                    <label htmlFor="custom-model" className="label">Custom model ID</label>
                    <input
                      id="custom-model"
                      type="text"
                      className="settings-custom-input"
                      placeholder={currentModel || 'e.g. gemini-2.5-pro-preview-06-05'}
                      value={customModel}
                      onChange={(e) => setCustomModel(e.target.value)}
                    />
                    {isCustom && !customModel && (
                      <span className="settings-current-note muted small">
                        Current: <code>{currentModel}</code> (custom)
                      </span>
                    )}
                  </div>
                </fieldset>

                {/* Embedding model selector */}
                <fieldset className="settings-fieldset">
                  <legend className="label">Knowledge Base · Embedding Model</legend>
                  <p className="muted small settings-embed-note">
                    Changing the embedding model requires a graph rebuild to take effect.
                  </p>
                  <div className="settings-embed-grid">
                    {EMBEDDING_OPTIONS.map((opt) => (
                      <label
                        key={opt.value}
                        className={`settings-embed-card ${draft.embedding_model === opt.value ? 'selected' : ''}`}
                      >
                        <input
                          type="radio"
                          name="embedding_model"
                          value={opt.value}
                          checked={draft.embedding_model === opt.value}
                          onChange={() => setDraft((d) => d && { ...d, embedding_model: opt.value })}
                        />
                        <span className="settings-embed-label">{opt.label}</span>
                        <span className="settings-embed-dim muted small">{opt.dim}d</span>
                      </label>
                    ))}
                  </div>
                </fieldset>

                {/* Actions */}
                <div className="settings-actions">
                  <button type="button" className="secondary" onClick={() => setOpen(false)}>
                    Cancel
                  </button>
                  <button
                    id="settings-save-btn"
                    type="button"
                    className="btn-primary"
                    onClick={handleSave}
                    disabled={saving}
                  >
                    {saving ? 'Saving…' : 'Apply'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}
