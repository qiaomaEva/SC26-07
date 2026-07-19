import { useEffect, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  PlugZap,
  RotateCcw,
  X,
} from 'lucide-react'
import { testModel, type LLMConfig } from '../api/client'

type Props = {
  config: LLMConfig
  onSave: (config: LLMConfig) => void
  onReset: () => void
  onClose: () => void
}

type TestState =
  | { kind: 'idle'; message: '' }
  | { kind: 'testing'; message: string }
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string }

function normalizeConfig(config: LLMConfig): LLMConfig {
  return {
    api_key: config.api_key.trim(),
    base_url: config.base_url.trim().replace(/\/+$/, ''),
    model: config.model.trim(),
    timeout_seconds: config.timeout_seconds,
  }
}

function validateConfig(config: LLMConfig): string {
  if (!config.api_key) return '请填写 API Key'
  if (!config.base_url) return '请填写 Base URL'
  if (!config.model) return '请填写模型名称'
  if (
    !Number.isFinite(config.timeout_seconds) ||
    config.timeout_seconds < 5 ||
    config.timeout_seconds > 300
  ) {
    return '超时时间必须在 5–300 秒之间'
  }
  try {
    const url = new URL(config.base_url)
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('invalid protocol')
  } catch {
    return 'Base URL 必须是有效的 HTTP(S) 地址'
  }
  return ''
}

export function ModelSettingsModal({ config, onSave, onReset, onClose }: Props) {
  const [draft, setDraft] = useState(config)
  const [showKey, setShowKey] = useState(false)
  const [testState, setTestState] = useState<TestState>({ kind: 'idle', message: '' })

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const update = <K extends keyof LLMConfig>(key: K, value: LLMConfig[K]) => {
    setDraft((previous) => ({ ...previous, [key]: value }))
    setTestState({ kind: 'idle', message: '' })
  }

  const onTest = async () => {
    const normalized = normalizeConfig(draft)
    const validationError = validateConfig(normalized)
    if (validationError) {
      setTestState({ kind: 'error', message: validationError })
      return
    }
    setTestState({
      kind: 'testing',
      message: `正在连接模型（最长 ${normalized.timeout_seconds} 秒）…`,
    })
    try {
      const result = await testModel(normalized)
      setTestState({
        kind: 'success',
        message: result.message ? `连接成功 · ${result.message}` : '连接成功',
      })
    } catch (error) {
      setTestState({
        kind: 'error',
        message: error instanceof Error ? error.message : String(error),
      })
    }
  }

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalized = normalizeConfig(draft)
    const validationError = validateConfig(normalized)
    if (validationError) {
      setTestState({ kind: 'error', message: validationError })
      return
    }
    onSave(normalized)
    onClose()
  }

  return (
    <div
      className="model-settings-mask"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        className="model-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-settings-title"
      >
        <div className="model-settings-head">
          <div>
            <h2 id="model-settings-title">模型设置</h2>
            <p>OpenAI 兼容接口</p>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} title="关闭">
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <form className="model-settings-form" onSubmit={onSubmit}>
          <label className="model-field">
            <span>API Key</span>
            <div className="secret-input">
              <input
                type={showKey ? 'text' : 'password'}
                value={draft.api_key}
                onChange={(event) => update('api_key', event.target.value)}
                placeholder="sk-..."
                autoComplete="new-password"
                autoFocus
              />
              <button
                type="button"
                className="secret-toggle"
                onClick={() => setShowKey((value) => !value)}
                title={showKey ? '隐藏 API Key' : '显示 API Key'}
                aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
              >
                {showKey ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
          </label>

          <label className="model-field">
            <span>Base URL</span>
            <input
              type="url"
              value={draft.base_url}
              onChange={(event) => update('base_url', event.target.value)}
              placeholder="https://api.deepseek.com"
            />
          </label>

          <label className="model-field">
            <span>模型名称</span>
            <input
              value={draft.model}
              onChange={(event) => update('model', event.target.value)}
              placeholder="deepseek-chat"
            />
          </label>

          <label className="model-field model-timeout-field">
            <span>超时时间</span>
            <div className="model-number-input">
              <input
                type="number"
                min="5"
                max="300"
                step="1"
                value={Number.isFinite(draft.timeout_seconds) ? draft.timeout_seconds : ''}
                onChange={(event) => update('timeout_seconds', event.target.valueAsNumber)}
                inputMode="numeric"
              />
              <span>秒</span>
            </div>
          </label>

          <p className="model-security-note">
            API Key 仅保存在当前浏览器会话，不会写入服务端配置或聊天记录。
          </p>

          {testState.kind !== 'idle' && (
            <div className={`model-test-result ${testState.kind}`} role="status">
              {testState.kind === 'success' ? (
                <CheckCircle2 size={16} aria-hidden="true" />
              ) : testState.kind === 'error' ? (
                <AlertCircle size={16} aria-hidden="true" />
              ) : (
                <span className="model-test-spinner" aria-hidden="true" />
              )}
              <span>{testState.message}</span>
            </div>
          )}

          <div className="model-settings-actions">
            <button
              type="button"
              className="btn-sm model-reset"
              onClick={() => {
                onReset()
                onClose()
              }}
            >
              <RotateCcw size={15} aria-hidden="true" />
              后端默认
            </button>
            <div className="model-primary-actions">
              <button
                type="button"
                className="btn-sm"
                onClick={() => void onTest()}
                disabled={testState.kind === 'testing'}
              >
                <PlugZap size={15} aria-hidden="true" />
                测试连接
              </button>
              <button type="submit" className="btn-sm accent">
                保存
              </button>
            </div>
          </div>
        </form>
      </section>
    </div>
  )
}
