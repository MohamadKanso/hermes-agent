import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'

import { renderSync } from '@hermes/ink'
import React, { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { InputEvent } from '../../packages/hermes-ink/src/ink/events/input-event.js'
import { INITIAL_STATE, parseMultipleKeypresses } from '../../packages/hermes-ink/src/ink/parse-keypress.js'
import { deleteCharForward, TextInput } from '../components/textInput.js'

function parseOne(sequence: string) {
  const [keys] = parseMultipleKeypresses(INITIAL_STATE, sequence)
  expect(keys).toHaveLength(1)

  return keys[0]!
}

class FakeInput extends EventEmitter {
  chunks: string[] = []
  isRaw = false
  isTTY = true
  readableLength = 0

  read() {
    const next = this.chunks.shift() ?? null
    this.readableLength = this.chunks.length

    return next
  }

  ref = vi.fn()

  send(...chunks: string[]) {
    this.chunks.push(...chunks)
    this.readableLength = this.chunks.length
    this.emit('readable')
  }

  setEncoding = vi.fn()

  setRawMode = vi.fn((enabled: boolean) => {
    this.isRaw = enabled
  })

  unref = vi.fn()
}

const settle = (ms = 25) => new Promise(resolve => setTimeout(resolve, ms))

function makeStreams() {
  const stdin = new FakeInput()
  const stdout = new PassThrough()
  const stderr = new PassThrough()

  Object.assign(stdout, { columns: 80, isTTY: false, rows: 24 })
  Object.assign(stderr, { columns: 80, isTTY: false, rows: 24 })

  return { stderr, stdin, stdout }
}

describe('ctrl+d keypress parsing', () => {
  it('parses raw byte 0x04 as ctrl+d', () => {
    const event = new InputEvent(parseOne('\x04'))

    expect(event.key.ctrl).toBe(true)
    expect(event.key.meta).toBe(false)
    expect(event.input).toBe('d')
  })
})

describe('deleteCharForward', () => {
  it('deletes character at start of buffer', () => {
    const result = deleteCharForward('hello', 0)

    expect(result.cursor).toBe(0)
    expect(result.value).toBe('ello')
  })

  it('deletes character in middle of buffer', () => {
    const result = deleteCharForward('hello', 2)

    expect(result.cursor).toBe(2)
    expect(result.value).toBe('helo')
  })

  it('deletes single character before end of buffer', () => {
    const result = deleteCharForward('hello', 4)

    expect(result.cursor).toBe(4)
    expect(result.value).toBe('hell')
  })

  it('is a no-op when cursor is at end of buffer', () => {
    const result = deleteCharForward('hello', 5)

    expect(result.cursor).toBe(5)
    expect(result.value).toBe('hello')
  })

  it('handles empty string gracefully', () => {
    const result = deleteCharForward('', 0)

    expect(result.cursor).toBe(0)
    expect(result.value).toBe('')
  })

  it('deletes full unicode grapheme cluster instead of splitting code units', () => {
    const result = deleteCharForward('✨ test', 0)

    expect(result.cursor).toBe(0)
    expect(result.value).toBe(' test')
  })
})

describe('TextInput ctrl+d forward delete', () => {
  it('deletes character under cursor when text exists and does not type letter d', async () => {
    const streams = makeStreams()
    const changes: string[] = []

    function Harness() {
      const [value, setValue] = useState('')

      return (
        <TextInput
          columns={80}
          onChange={next => {
            changes.push(next)
            setValue(next)
          }}
          onSubmit={() => {}}
          value={value}
        />
      )
    }

    const instance = renderSync(React.createElement(Harness), {
      patchConsole: false,
      stderr: streams.stderr as NodeJS.WriteStream,
      stdin: streams.stdin as unknown as NodeJS.ReadStream,
      stdout: streams.stdout as NodeJS.WriteStream
    })

    await settle()

    streams.stdin.send('a', 'b', 'c')
    await settle()
    expect(changes.at(-1)).toBe('abc')

    // move left twice so cursor is at position 1 (between 'a' and 'b')
    streams.stdin.send('\x1b[D')
    await settle()
    streams.stdin.send('\x1b[D')
    await settle()

    // send ctrl+d (byte 0x04)
    streams.stdin.send('\x04')
    await settle()

    instance.unmount()
    instance.cleanup()

    // should have deleted 'b' under cursor, leaving 'ac' without inserting 'd'
    expect(changes.at(-1)).toBe('ac')
    expect(changes).not.toContain('abcd')
  })

  it('does nothing when cursor is at end of buffer', async () => {
    const streams = makeStreams()
    const changes: string[] = []

    function Harness() {
      const [value, setValue] = useState('')

      return (
        <TextInput
          columns={80}
          onChange={next => {
            changes.push(next)
            setValue(next)
          }}
          onSubmit={() => {}}
          value={value}
        />
      )
    }

    const instance = renderSync(React.createElement(Harness), {
      patchConsole: false,
      stderr: streams.stderr as NodeJS.WriteStream,
      stdin: streams.stdin as unknown as NodeJS.ReadStream,
      stdout: streams.stdout as NodeJS.WriteStream
    })

    await settle()

    streams.stdin.send('f', 'o', 'o')
    await settle()
    expect(changes.at(-1)).toBe('foo')

    // cursor is at end (position 3). sending ctrl+d should be no-op and never insert 'd'
    streams.stdin.send('\x04')
    await settle()

    instance.unmount()
    instance.cleanup()

    expect(changes.at(-1)).toBe('foo')
    expect(changes).not.toContain('food')
  })

  it('deletes selected text range on ctrl+d', async () => {
    const streams = makeStreams()
    const changes: string[] = []

    function Harness() {
      const [value, setValue] = useState('')

      return (
        <TextInput
          columns={80}
          onChange={next => {
            changes.push(next)
            setValue(next)
          }}
          onSubmit={() => {}}
          value={value}
        />
      )
    }

    const instance = renderSync(React.createElement(Harness), {
      patchConsole: false,
      stderr: streams.stderr as NodeJS.WriteStream,
      stdin: streams.stdin as unknown as NodeJS.ReadStream,
      stdout: streams.stdout as NodeJS.WriteStream
    })

    await settle()

    streams.stdin.send('b', 'a', 'r')
    await settle()
    expect(changes.at(-1)).toBe('bar')

    // select with shift+left
    streams.stdin.send('\x1b[1;2D')
    await settle()

    // send ctrl+d
    streams.stdin.send('\x04')
    await settle()

    instance.unmount()
    instance.cleanup()

    expect(changes.at(-1)).toBe('ba')
  })
})
