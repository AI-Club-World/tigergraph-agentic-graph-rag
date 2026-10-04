import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, STALE_BACKEND, get } from './http'

afterEach(() => vi.unstubAllGlobals())

describe('API errors', () => {
  it('turn a FastAPI validation list into a readable message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: [{ loc: ['body', 'model'], msg: 'Field required' }] }),
      { status: 422, statusText: '' },
    )))
    const error = await get('/x').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('model: Field required')
  })

  it('keep the structured detail of a conflict', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: { code: 'embedding_mismatch', message: 'No.', available: [] } }),
      { status: 409 },
    )))
    const error = (await get('/x').catch((e: unknown) => e)) as ApiError
    expect(error.code).toBe('embedding_mismatch')
    expect(error.detail?.available).toEqual([])
  })

  it('explain a 401 as an outdated backend, since the application has no sign-in', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: 'Sign in required (missing or invalid credentials)' }),
      { status: 401 },
    )))
    const error = (await get('/corpora').catch((e: unknown) => e)) as ApiError
    expect(error.status).toBe(401)
    expect(error.message).toBe(STALE_BACKEND)
  })
})
