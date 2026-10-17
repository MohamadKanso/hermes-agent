import { useStore } from '@nanostores/react'
import { useQuery } from '@tanstack/react-query'

import { useDebounced } from '@/app/hooks/use-debounced'
import type { ResolvedOwner } from '@/api/client'
import { getCommandTtsVoices, profileScopeKey } from '@/hermes'
import { useI18n } from '@/i18n'
import { $activeConnectionId } from '@/store/connections'
import { $activeGatewayProfile } from '@/store/profile'
import type { HermesConfigRecord } from '@/types/hermes'

import { ConfigField } from './config-field'
import { getNested, selectedCommandTtsVoiceProvider, setNested } from './helpers'

export function commandTtsVoiceQueryKey(
  profile: null | string | undefined,
  connectionId: null | string,
  activeProfile: string,
  provider: null | string,
  configSignature = ''
) {
  const scope = profile === undefined ? ['ambient', activeProfile] : ['profile', profileScopeKey(profile)]

  return ['command-tts-voices', connectionId, scope, provider, configSignature] as const
}

export function commandTtsVoiceRequestOwner(
  profile: null | string | undefined,
  connectionId: null | string
): ResolvedOwner {
  return { connectionId, profile: profile === undefined ? null : profile }
}

export function commandTtsVoiceConfigSignature(
  config: HermesConfigRecord,
  provider: ReturnType<typeof selectedCommandTtsVoiceProvider>
): string {
  if (!provider) {
    return ''
  }

  const providerValue = getNested(config, provider.configPath)
  const providerConfig =
    providerValue !== null && typeof providerValue === 'object' && !Array.isArray(providerValue)
      ? (providerValue as Record<string, unknown>)
      : {}
  const ttsValue = getNested(config, 'tts')
  const ttsConfig =
    ttsValue !== null && typeof ttsValue === 'object' && !Array.isArray(ttsValue)
      ? (ttsValue as Record<string, unknown>)
      : {}
  const input = JSON.stringify([
    providerConfig.voices_command ?? null,
    providerConfig.voice ?? null,
    providerConfig.model ?? null,
    providerConfig.speed ?? null,
    providerConfig.format ?? null,
    providerConfig.output_format ?? null,
    providerConfig.timeout ?? null,
    providerConfig.timeout_seconds ?? null,
    providerConfig.env_passthrough ?? null,
    ttsConfig.speed ?? null
  ])
  let firstHash = 0x811c9dc5
  let secondHash = 0x9e3779b9

  for (let index = 0; index < input.length; index += 1) {
    const code = input.charCodeAt(index)
    firstHash = Math.imul(firstHash ^ code, 0x01000193)
    secondHash = Math.imul(secondHash ^ code, 0x85ebca6b)
  }

  return `${input.length}:${(firstHash >>> 0).toString(36)}:${(secondHash >>> 0).toString(36)}`
}

export function CommandTtsVoiceField({
  config,
  onChange,
  profile
}: {
  config: HermesConfigRecord
  onChange: (config: HermesConfigRecord) => void
  profile?: null | string
}) {
  const { t } = useI18n()
  const connectionId = useStore($activeConnectionId)
  const activeProfile = useStore($activeGatewayProfile)
  const provider = selectedCommandTtsVoiceProvider(config)
  const requestOwner = commandTtsVoiceRequestOwner(profile, connectionId)
  const configSignature = commandTtsVoiceConfigSignature(config, provider)
  const debouncedConfigSignature = useDebounced(configSignature, 350)
  const configIsSettled = configSignature === debouncedConfigSignature
  const { data, isRefetchError } = useQuery({
    queryKey: commandTtsVoiceQueryKey(
      profile,
      connectionId,
      activeProfile,
      provider?.name ?? null,
      debouncedConfigSignature
    ),
    queryFn: () => {
      if (!provider) {
        throw new Error('command TTS provider is not configured')
      }

      return getCommandTtsVoices(provider.name, requestOwner)
    },
    enabled: Boolean(provider?.hasVoiceCommand && configIsSettled),
    retry: false,
    // passthrough values stay server-side, so refresh cached results on revisit or focus
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always'
  })

  if (!provider) {
    return null
  }

  const voicePath = [...provider.configPath, 'voice']
  const schemaKey = voicePath.join('.')
  const configuredVoice = getNested(config, voicePath)
  const current = String(configuredVoice ?? data?.current ?? '').trim()
  const voices = configIsSettled && !isRefetchError && data?.available ? data.voices : []
  const options = [...new Set([...voices.map(voice => voice.id), current].filter(Boolean))]
  const optionLabels = Object.fromEntries(voices.map(voice => [voice.id, voice.label]))

  return (
    <ConfigField
      allowCustomOptions
      enumOptions={options}
      labelOverride={t.settings.sections.voice}
      onChange={value => onChange(setNested(config, voicePath, String(value ?? '')))}
      optionLabels={optionLabels}
      schema={{ type: 'string' }}
      schemaKey={schemaKey}
      value={current}
    />
  )
}
