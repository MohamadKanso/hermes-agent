import assert from 'node:assert/strict'

import { test } from 'vitest'

import { claimPrimaryBackendRecovery, type PrimaryBackendRecoveryState } from './backend-primary-recovery'

function recoveryState(overrides: Partial<PrimaryBackendRecoveryState> = {}): PrimaryBackendRecoveryState {
  return {
    hasCurrentProcess: false,
    hasPendingPrimaryStart: false,
    intentionalTeardown: false,
    recoveryClaimed: false,
    ...overrides
  }
}

test('claims recovery when the primary backend is gone', () => {
  assert.equal(claimPrimaryBackendRecovery(recoveryState()), true)
})

test('does not recover while a newer primary process is still attached', () => {
  assert.equal(claimPrimaryBackendRecovery(recoveryState({ hasCurrentProcess: true })), false)
})

test('does not recover while a primary replacement is pending', () => {
  assert.equal(claimPrimaryBackendRecovery(recoveryState({ hasPendingPrimaryStart: true })), false)
})

test('pool activity does not block a primary recovery claim', () => {
  // pool children are deliberately not part of this state. they do not own
  // the primary window backend and must not suppress its recovery.
  assert.equal(claimPrimaryBackendRecovery(recoveryState()), true)
})

test('does not recover during intentional teardown', () => {
  assert.equal(claimPrimaryBackendRecovery(recoveryState({ intentionalTeardown: true })), false)
})

test('coalesces repeated recovery events', () => {
  const state = recoveryState()

  assert.equal(claimPrimaryBackendRecovery(state), true)
  assert.equal(claimPrimaryBackendRecovery(state), false)
})
