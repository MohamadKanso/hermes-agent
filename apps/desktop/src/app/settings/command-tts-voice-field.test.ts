import { describe, expect, it } from 'vitest'

import {
  commandTtsVoiceConfigSignature,
  commandTtsVoiceQueryKey,
  commandTtsVoiceRequestOwner
} from './command-tts-voice-field'
import { selectedCommandTtsVoiceProvider } from './helpers'

describe('commandTtsVoiceQueryKey', () => {
  it('keeps ambient custom homes separate from named profiles and other gateways', () => {
    const ambientCustom = commandTtsVoiceQueryKey(undefined, null, 'custom', 'piper-custom')
    const namedDefault = commandTtsVoiceQueryKey('default', null, 'default', 'piper-custom')
    const remoteDefault = commandTtsVoiceQueryKey('default', 'remote-gateway', 'default', 'piper-custom')

    expect(ambientCustom).not.toEqual(namedDefault)
    expect(namedDefault).not.toEqual(remoteDefault)
  })

  it('pins a deferred query to the owner captured when its cache key was built', () => {
    let connectionId: null | string = 'gateway-a'
    let profile = 'profile-a'
    const capturedOwner = commandTtsVoiceRequestOwner(profile, connectionId)
    const queryKey = commandTtsVoiceQueryKey(profile, connectionId, 'active-a', 'piper-custom')

    connectionId = 'gateway-b'
    profile = 'profile-b'

    expect(queryKey).toContain('gateway-a')
    expect(capturedOwner).toEqual({ connectionId: 'gateway-a', profile: 'profile-a' })
  })

  it('keeps custom homes ambient instead of treating them as named profiles', () => {
    expect(commandTtsVoiceRequestOwner(undefined, null)).toEqual({
      connectionId: null,
      profile: null
    })
  })

  it('keys discovery by a private fingerprint of settings that affect the voice list', () => {
    const config = {
      tts: {
        provider: 'piper-custom',
        providers: {
          'piper-custom': {
            type: 'command',
            command: 'piper speak',
            voices_command: 'piper --voices --current {voice}',
            voice: 'private-voice-token',
            model: 'model-a'
          }
        }
      }
    }
    const provider = selectedCommandTtsVoiceProvider(config)
    const signature = commandTtsVoiceConfigSignature(config, provider)
    const changed = structuredClone(config)
    changed.tts.providers['piper-custom'].model = 'model-b'

    expect(signature).not.toContain('private-voice-token')
    expect(commandTtsVoiceConfigSignature(changed, provider)).not.toBe(signature)
    expect(commandTtsVoiceQueryKey('default', null, 'default', 'piper-custom', signature)).not.toEqual(
      commandTtsVoiceQueryKey('default', null, 'default', 'piper-custom', 'changed')
    )
  })
})
