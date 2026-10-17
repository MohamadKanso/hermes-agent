import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $notifications, clearNotifications } from '@/store/notifications'
import type { ModelAssignmentRequest } from '@/types/hermes'

import { setMainModelAssignment, setModelAssignmentWithGuards } from './model-assignment'

const setModelAssignmentMock = vi.fn()

vi.mock('@/hermes', () => ({
  setModelAssignment: (body: ModelAssignmentRequest, profile?: string) =>
    setModelAssignmentMock(body, profile)
}))

describe('model-assignment store helpers', () => {
  beforeEach(() => {
    clearNotifications()
    vi.clearAllMocks()
  })

  afterEach(() => {
    clearNotifications()
  })

  it('delegates setMainModelAssignment to main scope', async () => {
    setModelAssignmentMock.mockResolvedValueOnce({
      ok: true,
      scope: 'main',
      provider: 'nous',
      model: 'hermes-4'
    })

    const res = await setMainModelAssignment({ provider: 'nous', model: 'hermes-4' })
    expect(res.ok).toBe(true)
    expect(setModelAssignmentMock).toHaveBeenCalledWith(
      {
        provider: 'nous',
        model: 'hermes-4',
        scope: 'main'
      },
      undefined
    )
  })

  it('prompts on confirm_required and retries with confirm_expensive_model on auxiliary task', async () => {
    setModelAssignmentMock
      .mockResolvedValueOnce({
        ok: false,
        scope: 'auxiliary',
        task: 'vision',
        provider: 'nous',
        model: 'hermes-4-contributor',
        confirm_required: true,
        confirm_message: 'this model logs prompts for training'
      })
      .mockResolvedValueOnce({
        ok: true,
        scope: 'auxiliary',
        task: 'vision',
        provider: 'nous',
        model: 'hermes-4-contributor'
      })

    const promise = setModelAssignmentWithGuards({
      scope: 'auxiliary',
      task: 'vision',
      provider: 'nous',
      model: 'hermes-4-contributor'
    })

    // wait for first assignment promise to settle and trigger the confirm warning
    await Promise.resolve()
    await Promise.resolve()

    const notifications = $notifications.get()
    expect(notifications.length).toBe(1)
    expect(notifications[0].kind).toBe('warning')

    notifications[0].action?.onClick?.()

    const res = await promise
    expect(res.ok).toBe(true)
    expect(setModelAssignmentMock).toHaveBeenCalledTimes(2)
    expect(setModelAssignmentMock).toHaveBeenNthCalledWith(
      2,
      {
        scope: 'auxiliary',
        task: 'vision',
        provider: 'nous',
        model: 'hermes-4-contributor',
        confirm_expensive_model: true
      },
      undefined
    )
  })

  it('throws declined error when confirm prompt is dismissed', async () => {
    setModelAssignmentMock.mockResolvedValueOnce({
      ok: false,
      scope: 'auxiliary',
      task: 'vision',
      provider: 'nous',
      model: 'expensive-tier',
      confirm_required: true,
      confirm_message: 'pricing warning'
    })

    const promise = setModelAssignmentWithGuards({
      scope: 'auxiliary',
      task: 'vision',
      provider: 'nous',
      model: 'expensive-tier'
    })

    await Promise.resolve()
    await Promise.resolve()

    const notifications = $notifications.get()
    expect(notifications.length).toBe(1)

    notifications[0].onDismiss?.()

    await expect(promise).rejects.toThrow()
    expect(setModelAssignmentMock).toHaveBeenCalledTimes(1)
  })

  it('fails immediately without prompt when skipConfirmPrompt is set', async () => {
    setModelAssignmentMock.mockResolvedValueOnce({
      ok: false,
      scope: 'auxiliary',
      task: 'vision',
      provider: 'nous',
      model: 'expensive-tier',
      confirm_required: true,
      confirm_message: 'pricing warning'
    })

    await expect(
      setModelAssignmentWithGuards(
        {
          scope: 'auxiliary',
          task: 'vision',
          provider: 'nous',
          model: 'expensive-tier'
        },
        undefined,
        { skipConfirmPrompt: true }
      )
    ).rejects.toThrow('pricing warning')

    expect($notifications.get().length).toBe(0)
  })
})
