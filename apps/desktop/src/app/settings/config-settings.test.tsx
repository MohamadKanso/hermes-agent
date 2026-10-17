import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { atom } from 'nanostores'
import { createRef } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type * as ConfigApi from '@/api/config'
import { $activeConnectionId } from '@/store/connections'
import { $settingsRequestProfile } from '@/store/settings-scope'

import type { ConfigSettings as ConfigSettingsType } from './config-settings'

// The vi.mock factory below replaces the computed (read-only) atom with a
// writable one; narrow the import back so tests can drive it.
const scopeProfileMock = $settingsRequestProfile as unknown as { set: (value: string) => void }
const connectionIdMock = $activeConnectionId as unknown as { set: (value: null | string) => void }

const getHermesConfigRecord = vi.fn()
const getHermesConfigSchema = vi.fn()
const saveHermesConfig = vi.fn()
const getElevenLabsVoices = vi.fn()
const getCommandTtsVoices = vi.fn()

// Keep the real read-origin helpers (WeakMap peek/bind) live: the shared
// config hook reaches them through the barrel, and a bare mock would throw.
vi.mock('@/hermes', async () => ({
  ...(await vi.importActual<typeof ConfigApi>('@/api/config')),
  // use-config-record folds the scope into its cache key via the barrel; the
  // real one is a pure string fold, mirrored here for the string scopes this
  // suite passes.
  profileScopeKey: (scope?: unknown) => (typeof scope === 'string' && scope.trim()) || 'default',
  getHermesConfigRecord: (profile?: string) => getHermesConfigRecord(profile),
  getHermesConfigSchema: () => getHermesConfigSchema(),
  saveHermesConfig: (config: unknown, profile?: string) => saveHermesConfig(config, profile),
  getElevenLabsVoices: () => getElevenLabsVoices(),
  getCommandTtsVoices: (provider: string, profile?: string) => getCommandTtsVoices(provider, profile),
  setApiRequestProfile: () => {}
}))

vi.mock('../hooks/use-on-profile-switch', () => ({
  useOnProfileSwitch: () => {}
}))

// The real stores pull in the gateway/profile stack, which needs a live
// backend connection. This page only reads the "applies to" scope override
// and the repo-discovery signature, neither of which this test touches. The
// scope chip it renders also reads the selected profile and the loud-note
// selector, so those are stubbed to the single-profile default shape.
vi.mock('@/store/settings-scope', () => ({
  // The real store derives this from the displayed $settingsScopeProfile
  // (never undefined for a real profile — settings-scope.test.ts pins that);
  // here it is a plain atom so the page's threading of it can be driven.
  $settingsRequestProfile: atom<string | undefined>('default'),
  $settingsScopeEditsNonDefault: atom(false),
  $settingsScopeOverride: atom<null | string>(null),
  $settingsScopeProfile: atom<string>('default')
}))

vi.mock('@/store/connections', async () => ({
  ...(await vi.importActual<typeof import('@/store/connections')>('@/store/connections')),
  $activeConnectionId: atom<null | string>(null)
}))

vi.mock('@/store/projects', () => ({
  $worktreeRefreshToken: atom(0),
  repoDiscoveryPolicyFromConfig: () => ({ enabled: true, roots: [], exclude_paths: [] }),
  repoDiscoveryPolicySignature: (policy: unknown) => JSON.stringify(policy),
  scanAndRecordRepos: vi.fn().mockResolvedValue(undefined)
}))

// The module graph behind ConfigSettings is large (1.5s cold here, >10s on a
// saturated CI runner); load it once under the hook timeout so the 15s test
// budget is spent on the autosave behaviour, not on transform + import.
let ConfigSettings: typeof ConfigSettingsType

beforeAll(async () => {
  ;({ ConfigSettings } = await import('./config-settings'))
}, 60_000)

beforeEach(() => {
  scopeProfileMock.set('default')
  connectionIdMock.set(null)
  getElevenLabsVoices.mockResolvedValue({ available: false })
  getCommandTtsVoices.mockResolvedValue({ available: false, provider: '', current: '', voices: [] })
  getHermesConfigSchema.mockResolvedValue({ fields: {} })
  saveHermesConfig.mockResolvedValue({ ok: true })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderConfigSettings(activeSectionId = 'safety') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const importInputRef = createRef<HTMLInputElement>()

  render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <ConfigSettings activeSectionId={activeSectionId} importInputRef={importInputRef} />
      </QueryClientProvider>
    </MemoryRouter>
  )

  return { importInputRef }
}

describe('ConfigSettings autosave', () => {
  it('loads command-provider voices for the selected profile', async () => {
    getHermesConfigRecord.mockResolvedValue({
      tts: {
        provider: 'piper-custom',
        providers: {
          'piper-custom': {
            type: 'command',
            command: 'piper speak',
            voices_command: 'piper --list-voices',
            voice: 'en_US-amy-medium'
          }
        }
      }
    })
    getHermesConfigSchema.mockResolvedValue({ fields: { 'tts.provider': { type: 'select', options: [] } } })
    getCommandTtsVoices.mockResolvedValue({
      available: true,
      provider: 'piper-custom',
      current: 'en_US-amy-medium',
      voices: [{ id: 'en_US-amy-medium', label: 'en_US-amy-medium' }]
    })

    renderConfigSettings('voice')

    await vi.waitFor(() =>
      expect(getCommandTtsVoices).toHaveBeenCalledWith('piper-custom', { connectionId: null, profile: 'default' })
    )
    await vi.waitFor(() =>
      expect(document.querySelector('[data-tour="field-tts.providers.piper-custom.voice"]')).not.toBeNull()
    )
  })

  it('keeps the command voice field editable when discovery is unavailable', async () => {
    getHermesConfigRecord.mockResolvedValue({
      tts: {
        provider: 'piper-custom',
        providers: {
          'piper-custom': {
            type: 'command',
            command: 'piper speak',
            voices_command: 'piper --list-voices',
            voice: ''
          }
        }
      }
    })
    getHermesConfigSchema.mockResolvedValue({ fields: { 'tts.provider': { type: 'select', options: [] } } })

    renderConfigSettings('voice')

    await vi.waitFor(() =>
      expect(getCommandTtsVoices).toHaveBeenCalledWith('piper-custom', { connectionId: null, profile: 'default' })
    )
    await vi.waitFor(() => {
      const field = document.querySelector('[data-tour="field-tts.providers.piper-custom.voice"]')
      expect(field?.querySelector('[role="combobox"]')).not.toBeNull()
    })
  })

  it('shows a manual voice field when a command provider has no discovery command', async () => {
    getHermesConfigRecord.mockResolvedValue({
      tts: {
        provider: 'piper-custom',
        providers: {
          'piper-custom': {
            type: 'command',
            command: 'piper speak',
            voice: 'manual-voice'
          }
        }
      }
    })
    getHermesConfigSchema.mockResolvedValue({ fields: { 'tts.provider': { type: 'select', options: [] } } })

    renderConfigSettings('voice')

    await vi.waitFor(() =>
      expect(document.querySelector('[data-tour="field-tts.providers.piper-custom.voice"]')).not.toBeNull()
    )
    expect(screen.getByDisplayValue('manual-voice')).toBeTruthy()
    expect(getCommandTtsVoices).not.toHaveBeenCalled()
  })

  it('keeps empty discovery editable and saves a typed voice id', async () => {
    getHermesConfigRecord.mockResolvedValue({
      tts: {
        provider: 'piper-custom',
        providers: {
          'piper-custom': {
            type: 'command',
            command: 'piper speak',
            voices_command: 'piper --list-voices',
            voice: ''
          }
        }
      }
    })
    getHermesConfigSchema.mockResolvedValue({ fields: { 'tts.provider': { type: 'select', options: [] } } })
    getCommandTtsVoices.mockResolvedValue({
      available: true,
      provider: 'piper-custom',
      current: '',
      voices: []
    })
    vi.useFakeTimers({ shouldAdvanceTime: true })

    try {
      renderConfigSettings('voice')
      await vi.waitFor(() => expect(getCommandTtsVoices).toHaveBeenCalled())
      const input = document.querySelector('[data-tour="field-tts.providers.piper-custom.voice"] [role="combobox"]')
      expect(input).not.toBeNull()
      fireEvent.change(input!, { target: { value: 'manual-voice-id' } })
      await vi.advanceTimersByTimeAsync(700)

      await vi.waitFor(() => expect(saveHermesConfig).toHaveBeenCalled())
      expect(JSON.stringify(saveHermesConfig.mock.calls)).toContain('manual-voice-id')
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps the manual voice field available when discovery rejects', async () => {
    getHermesConfigRecord.mockResolvedValue({
      tts: {
        provider: 'piper-custom',
        providers: {
          'piper-custom': {
            type: 'command',
            command: 'piper speak',
            voices_command: 'piper --list-voices',
            voice: ''
          }
        }
      }
    })
    getHermesConfigSchema.mockResolvedValue({ fields: { 'tts.provider': { type: 'select', options: [] } } })
    getCommandTtsVoices.mockRejectedValueOnce(new Error('voice query failed'))

    renderConfigSettings('voice')

    await vi.waitFor(() =>
      expect(
        document.querySelector('[data-tour="field-tts.providers.piper-custom.voice"] [role="combobox"]')
      ).not.toBeNull()
    )
  })

  it('keeps deferred voice requests on the profile and connection that keyed them', async () => {
    type VoiceResponse = {
      available: boolean
      provider: string
      current: string
      voices: { id: string; label: string }[]
    }
    const pending: Array<(response: VoiceResponse) => void> = []

    scopeProfileMock.set('profile-a')
    connectionIdMock.set('gateway-a')
    getHermesConfigRecord.mockResolvedValue({
      tts: {
        provider: 'piper-custom',
        providers: {
          'piper-custom': {
            type: 'command',
            command: 'piper speak',
            voices_command: 'piper --list-voices',
            voice: 'current'
          }
        }
      }
    })
    getHermesConfigSchema.mockResolvedValue({ fields: { 'tts.provider': { type: 'select', options: [] } } })
    getCommandTtsVoices.mockImplementation(
      () => new Promise(resolve => pending.push(resolve as (response: VoiceResponse) => void))
    )

    renderConfigSettings('voice')

    await vi.waitFor(() => expect(getCommandTtsVoices).toHaveBeenCalledTimes(1))
    scopeProfileMock.set('profile-b')
    connectionIdMock.set('gateway-b')

    await vi.waitFor(() => expect(getCommandTtsVoices).toHaveBeenCalledTimes(2))
    expect(getCommandTtsVoices.mock.calls[0]).toEqual([
      'piper-custom',
      { connectionId: 'gateway-a', profile: 'profile-a' }
    ])
    expect(getCommandTtsVoices.mock.calls[1]).toEqual([
      'piper-custom',
      { connectionId: 'gateway-b', profile: 'profile-b' }
    ])

    await act(async () => {
      pending[0]({ available: true, provider: 'piper-custom', current: 'current', voices: [] })
      pending[1]({ available: true, provider: 'piper-custom', current: 'current', voices: [] })
    })
  })

  it('sends a later revert instead of diffing it away against the stale page-load baseline', async () => {
    getHermesConfigRecord.mockResolvedValue({ checkpoints: { enabled: false }, other: 'untouched' })

    vi.useFakeTimers({ shouldAdvanceTime: true })

    try {
      renderConfigSettings()

      const toggle = await screen.findByRole('switch')

      // Edit: flip checkpoints.enabled on, let the debounced autosave fire.
      toggle.click()
      await vi.advanceTimersByTimeAsync(700)

      await vi.waitFor(() => expect(saveHermesConfig).toHaveBeenCalledTimes(1))
      expect(saveHermesConfig.mock.calls[0][0]).toEqual({ checkpoints: { enabled: true } })

      // Revert: flip it back to its original value and let autosave fire again.
      toggle.click()
      await vi.advanceTimersByTimeAsync(700)

      await vi.waitFor(() => expect(saveHermesConfig).toHaveBeenCalledTimes(2))
      // Must still explicitly send the reverted value — diffing against the
      // never-advanced page-load baseline would produce an empty patch here
      // (the field is back to its original value) and leave disk stuck at
      // `enabled: true` from the first save.
      expect(saveHermesConfig.mock.calls[1][0]).toEqual({ checkpoints: { enabled: false } })
    } finally {
      vi.useRealTimers()
    }
  })

  it('threads the "Applies to" request scope into both the config read and the autosave write', async () => {
    // #118432: the request scope is the concrete profile the page displays
    // (see settings-scope.test.ts). The page must carry it into the read AND
    // the write — a read scoped to B with a write that falls back to the
    // ambient (launch) profile is exactly the silent cross-profile write.
    scopeProfileMock.set('nash')
    getHermesConfigRecord.mockResolvedValue({ checkpoints: { enabled: false } })

    vi.useFakeTimers({ shouldAdvanceTime: true })

    try {
      renderConfigSettings()

      await vi.waitFor(() => expect(getHermesConfigRecord).toHaveBeenCalledWith('nash'))

      ;(await screen.findByRole('switch')).click()
      await vi.advanceTimersByTimeAsync(700)

      await vi.waitFor(() => expect(saveHermesConfig).toHaveBeenCalledWith({ checkpoints: { enabled: true } }, 'nash'))
    } finally {
      vi.useRealTimers()
    }
  })
})
