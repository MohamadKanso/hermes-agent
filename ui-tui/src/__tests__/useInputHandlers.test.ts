import { describe, expect, it, vi } from 'vitest'

import { getOverlayState, patchOverlayState, resetOverlayState } from '../app/overlayStore.js'
import { rememberServerRequest, resetServerRequestsForTests } from '../app/serverRequestStore.js'
import {
  applyVoiceRecordResponse,
  dismissSensitivePrompt,
  handleIdleHotkeyExit,
  isCtrlDShortcut,
  resolveCtrlCComposerAction,
  shouldAllowIdleHotkeyExit,
  shouldDetachEditedHistoryInput,
  shouldExitOnCtrlD,
  shouldFallThroughForScroll
} from '../app/useInputHandlers.js'

const baseKey = {
  downArrow: false,
  pageDown: false,
  pageUp: false,
  shift: false,
  upArrow: false,
  wheelDown: false,
  wheelUp: false
}

describe('shouldFallThroughForScroll — keep transcript scrolling alive during prompt overlays', () => {
  it('falls through for wheel scrolls', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, wheelUp: true })).toBe(true)
    expect(shouldFallThroughForScroll({ ...baseKey, wheelDown: true })).toBe(true)
  })

  it('falls through for PageUp / PageDown', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, pageUp: true })).toBe(true)
    expect(shouldFallThroughForScroll({ ...baseKey, pageDown: true })).toBe(true)
  })

  it('falls through for Shift+ArrowUp / Shift+ArrowDown', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, shift: true, upArrow: true })).toBe(true)
    expect(shouldFallThroughForScroll({ ...baseKey, shift: true, downArrow: true })).toBe(true)
  })

  it('does NOT fall through for plain arrows — those drive in-prompt selection', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, upArrow: true })).toBe(false)
    expect(shouldFallThroughForScroll({ ...baseKey, downArrow: true })).toBe(false)
  })

  it('does NOT fall through for plain Shift — without an arrow it is a no-op', () => {
    expect(shouldFallThroughForScroll({ ...baseKey, shift: true })).toBe(false)
  })

  it('does NOT fall through for unrelated state (no scroll keys held)', () => {
    expect(shouldFallThroughForScroll(baseKey)).toBe(false)
  })
})

describe('shouldAllowIdleHotkeyExit', () => {
  it('keeps idle exit hotkeys enabled in normal terminals', () => {
    expect(shouldAllowIdleHotkeyExit(false)).toBe(true)
  })

  it('disables idle exit hotkeys in dashboard chat', () => {
    expect(shouldAllowIdleHotkeyExit(true)).toBe(false)
  })
})

describe('shouldDetachEditedHistoryInput', () => {
  const history = ['older message', 'line one\nline two']

  it('detaches a recalled entry as soon as the user edits it', () => {
    expect(shouldDetachEditedHistoryInput(1, history, 'line one edited\nline two')).toBe(true)
  })

  it('keeps unchanged recalled entries in history navigation', () => {
    expect(shouldDetachEditedHistoryInput(1, history, 'line one\nline two')).toBe(false)
  })

  it('does not detach an ordinary current draft', () => {
    expect(shouldDetachEditedHistoryInput(null, history, 'new draft')).toBe(false)
  })
})

describe('resolveCtrlCComposerAction — draft wins over interrupt', () => {
  it('clears a non-empty composer even while the agent is streaming', () => {
    expect(resolveCtrlCComposerAction({ busy: true, hasDraft: true, hasSession: true })).toBe('clear')
  })

  it('interrupts a running turn when the composer is empty', () => {
    expect(resolveCtrlCComposerAction({ busy: true, hasDraft: false, hasSession: true })).toBe('interrupt')
  })

  it('clears an idle composer instead of exiting', () => {
    expect(resolveCtrlCComposerAction({ busy: false, hasDraft: true, hasSession: true })).toBe('clear')
  })

  it('exits when idle with an empty composer', () => {
    expect(resolveCtrlCComposerAction({ busy: false, hasDraft: false, hasSession: true })).toBe('exit')
  })

  it('does not interrupt a busy session that has no sid yet', () => {
    expect(resolveCtrlCComposerAction({ busy: true, hasDraft: false, hasSession: false })).toBe('exit')
  })
})

describe('handleIdleHotkeyExit', () => {
  it('exits in normal terminals', () => {
    const actions = { die: vi.fn(), sys: vi.fn() }

    handleIdleHotkeyExit(actions, false)

    expect(actions.die).toHaveBeenCalledTimes(1)
    expect(actions.sys).not.toHaveBeenCalled()
  })

  it('asks the dashboard for a fresh chat instead of leaving a ghost session', () => {
    const actions = { die: vi.fn(), sys: vi.fn() }
    const requestDashboardNewSession = vi.fn()

    handleIdleHotkeyExit(actions, true, requestDashboardNewSession)

    expect(actions.die).not.toHaveBeenCalled()
    expect(requestDashboardNewSession).toHaveBeenCalledTimes(1)
    expect(actions.sys).toHaveBeenCalledWith('starting a fresh dashboard chat...')
  })
})

describe('isCtrlDShortcut', () => {
  it('recognizes ctrl+d on macos without requiring cmd modifier', () => {
    expect(isCtrlDShortcut({ ctrl: true, meta: false, super: false }, 'd')).toBe(true)
    expect(isCtrlDShortcut({ ctrl: true, meta: false, super: false }, 'D')).toBe(true)
  })

  it('recognizes literal eof control character', () => {
    expect(isCtrlDShortcut({ ctrl: true, meta: false, super: false }, '\x04')).toBe(true)
  })

  it('rejects cmd+d on macos so ghostty pane splitting is not intercepted', () => {
    expect(isCtrlDShortcut({ ctrl: false, meta: true, super: false }, 'd')).toBe(false)
    expect(isCtrlDShortcut({ ctrl: false, meta: false, super: true }, 'd')).toBe(false)
  })

  it('rejects alt+d and esc d so forward word deletion is not intercepted', () => {
    expect(isCtrlDShortcut({ ctrl: false, meta: true, super: false }, 'd')).toBe(false)
  })

  it('rejects plain d without modifier', () => {
    expect(isCtrlDShortcut({ ctrl: false, meta: false, super: false }, 'd')).toBe(false)
  })

  it('rejects other control chords', () => {
    expect(isCtrlDShortcut({ ctrl: true, meta: false, super: false }, 'c')).toBe(false)
    expect(isCtrlDShortcut({ ctrl: true, meta: false, super: false }, 'x')).toBe(false)
  })
})

describe('shouldExitOnCtrlD', () => {
  it('exits when idle with empty composer and no images', () => {
    expect(
      shouldExitOnCtrlD({
        busy: false,
        hasDraft: false,
        hasImages: false,
        hasTokens: false
      })
    ).toBe(true)
  })

  it('does not exit when the agent is streaming', () => {
    expect(
      shouldExitOnCtrlD({
        busy: true,
        hasDraft: false,
        hasImages: false,
        hasTokens: false
      })
    ).toBe(false)
  })

  it('does not exit when input has a draft', () => {
    expect(
      shouldExitOnCtrlD({
        busy: false,
        hasDraft: true,
        hasImages: false,
        hasTokens: false
      })
    ).toBe(false)
  })

  it('does not exit when composer has attached images', () => {
    expect(
      shouldExitOnCtrlD({
        busy: false,
        hasDraft: false,
        hasImages: true,
        hasTokens: true
      })
    ).toBe(false)
  })

  it('does not exit when composer has tokens', () => {
    expect(
      shouldExitOnCtrlD({
        busy: false,
        hasDraft: false,
        hasImages: false,
        hasTokens: true
      })
    ).toBe(false)
  })
})

describe('applyVoiceRecordResponse', () => {
  it('reverts optimistic REC state when the gateway reports voice busy', () => {
    const setProcessing = vi.fn()
    const setRecording = vi.fn()
    const sys = vi.fn()

    applyVoiceRecordResponse({ status: 'busy' }, true, { setProcessing, setRecording }, sys)

    expect(setRecording).toHaveBeenCalledWith(false)
    expect(setProcessing).toHaveBeenCalledWith(true)
    expect(sys).toHaveBeenCalledWith('voice: still transcribing; try again shortly')
  })

  it('keeps optimistic REC state for successful recording starts', () => {
    const setProcessing = vi.fn()
    const setRecording = vi.fn()

    applyVoiceRecordResponse({ status: 'recording' }, true, { setProcessing, setRecording }, vi.fn())

    expect(setRecording).not.toHaveBeenCalled()
    expect(setProcessing).not.toHaveBeenCalled()
  })

  it('reverts optimistic REC state when the gateway returns null', () => {
    const setProcessing = vi.fn()
    const setRecording = vi.fn()

    applyVoiceRecordResponse(null, true, { setProcessing, setRecording }, vi.fn())

    expect(setRecording).toHaveBeenCalledWith(false)
    expect(setProcessing).toHaveBeenCalledWith(false)
  })
})

describe('dismissSensitivePrompt', () => {
  const openRequest = (id: string, method: string) => {
    const respond = vi.fn()

    rememberServerRequest({ fail: vi.fn(), id, method, params: {}, respond })

    return respond
  }

  it('clears a sudo overlay and answers the server request with an empty value', () => {
    resetOverlayState()
    resetServerRequestsForTests()
    patchOverlayState({ sudo: { requestId: 'srq-sudo' } })
    const respond = openRequest('srq-sudo', 'sudo')
    const sys = vi.fn()

    dismissSensitivePrompt(getOverlayState(), vi.fn(), sys)

    expect(getOverlayState().sudo).toBeNull()
    expect(sys).toHaveBeenCalledWith('sudo cancelled')
    expect(respond).toHaveBeenCalledWith({ value: '' })
  })

  it('clears a secret overlay even when its request already expired (nothing left to answer)', () => {
    resetOverlayState()
    resetServerRequestsForTests()
    patchOverlayState({ secret: { envVar: 'API_KEY', prompt: 'Enter API key', requestId: 'srq-gone' } })
    const sys = vi.fn()

    dismissSensitivePrompt(getOverlayState(), vi.fn(), sys)

    expect(getOverlayState().secret).toBeNull()
    expect(sys).toHaveBeenCalledWith('secret entry cancelled')
  })
})
