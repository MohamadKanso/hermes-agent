export type PrimaryBackendRecoveryState = {
  hasCurrentProcess: boolean
  hasPendingPrimaryStart: boolean
  intentionalTeardown: boolean
  recoveryClaimed: boolean
}

export function claimPrimaryBackendRecovery(state: PrimaryBackendRecoveryState): boolean {
  if (state.hasCurrentProcess || state.hasPendingPrimaryStart || state.intentionalTeardown || state.recoveryClaimed) {
    return false
  }

  state.recoveryClaimed = true

  return true
}
