import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../config', async () => {
  const actual = await vi.importActual<typeof import('../config')>('../config')
  return { config: { ...actual.config, useMockApi: false, apiBaseUrl: 'http://api' } }
})

import { SessionControl, pageReload } from './SignIn'
import { authHeaders, sessionRejected, sessionToken, signIn, signOut } from '../services/session'

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

describe('sign-in session', () => {
  beforeEach(() => window.sessionStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('exchanges the typed key for a session token and sends only the token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(() => respond(200, { token: 'tok-1', role: 'viewer' }))
    expect(await signIn('the-key')).toBe('viewer')
    expect(fetchMock).toHaveBeenCalledWith('http://api/auth/session', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ key: 'the-key' }),
    }))
    expect(authHeaders()).toEqual({ Authorization: 'Bearer tok-1' })
    expect(JSON.stringify(window.sessionStorage)).not.toContain('the-key') // the key itself is never stored
    fetchMock.mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })))
    await signOut()
    expect(sessionToken()).toBeNull()
    expect(authHeaders()).toEqual({})
  })

  it('opens the dialog when there is no session, and again when one is rejected', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => respond(200, { token: 'tok-2', role: 'admin' }))
    const reload = vi.spyOn(pageReload, 'reload').mockImplementation(() => {})
    render(<SessionControl />)
    expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Access key'), { target: { value: 'admin-key' } })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByText('admin')).toBeTruthy()
    expect(reload).toHaveBeenCalledOnce() // screens fetched before sign-in reload with the session

    sessionRejected()
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Sign in' })).toBeTruthy())
    expect(screen.getByText(/session has ended/)).toBeTruthy()
    expect(sessionToken()).toBeNull()
  })

  it('shows the server’s reason for a refused key', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => respond(401, { detail: 'Wrong key' }))
    render(<SessionControl />)
    fireEvent.change(screen.getByLabelText('Access key'), { target: { value: 'guess' } })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Wrong key')
  })
})
