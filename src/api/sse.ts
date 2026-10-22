/**
 * SSE 流式问答客户端（docs/06 §5.8）。
 * 事件序列：meta（检索完成立即下发）→ token* → ping(15s) → done / error。
 * EventSource 不支持 POST 且 Axios 无法流式读取响应体，故保留 fetch + ReadableStream 手工解析。
 */
import type { QaAskPayload, QaMetaEvent, QaDoneEvent } from '../types'

export interface SseError {
  code: number
  message: string
}

export interface StreamHandlers {
  onMeta?: (data: QaMetaEvent) => void
  onToken?: (delta: string) => void
  onDone?: (data: QaDoneEvent) => void
  onError?: (data: SseError) => void
}

interface SseEvent<T = any> {
  event: string
  data: T
}

async function* parseSseStream(response: Response): AsyncGenerator<SseEvent> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep: number
      while ((sep = buffer.indexOf('\n\n')) >= 0) {
        const rawEvent = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        let event = 'message'
        let data = ''
        for (const line of rawEvent.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) data += line.slice(5).trim()
        }
        if (!data) continue
        try {
          yield { event, data: JSON.parse(data) }
        } catch {
          /* 忽略无法解析的块 */
        }
      }
    }
  } finally {
    reader.releaseLock?.()
  }
}

/**
 * 发起流式问答。
 * @param payload QaAskRequest（question/session_no/kb_ids/mode/top_k/use_history）
 * @param handlers { onMeta, onToken, onDone, onError }
 * @param controller 用于「停止生成」
 */
export async function streamAsk(
  payload: QaAskPayload,
  handlers: StreamHandlers,
  controller: AbortController,
): Promise<void> {
  const token = localStorage.getItem('lexfin_token') || ''
  let resp: Response
  try {
    resp = await fetch('/api/v1/qa/ask/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
  } catch (err) {
    if ((err as Error)?.name !== 'AbortError') {
      handlers.onError?.({ code: -1, message: (err as Error)?.message || '网络中断' })
    }
    return
  }

  if (!resp.ok || !resp.body) {
    let message = `连接失败（HTTP ${resp.status}）`
    try {
      const j = await resp.json()
      if (j?.message) message = j.message
    } catch {
      /* ignore */
    }
    handlers.onError?.({ code: resp.status, message })
    return
  }

  try {
    for await (const { event, data } of parseSseStream(resp)) {
      if (event === 'meta') handlers.onMeta?.(data)
      else if (event === 'token') handlers.onToken?.(data.delta || '')
      else if (event === 'done') handlers.onDone?.(data)
      else if (event === 'error') handlers.onError?.(data)
      // ping：保活事件，无需处理
    }
  } catch (err) {
    if ((err as Error)?.name !== 'AbortError') {
      handlers.onError?.({ code: -1, message: (err as Error)?.message || '网络中断' })
    }
  }
}
