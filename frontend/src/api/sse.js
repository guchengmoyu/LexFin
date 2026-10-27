/**
 * SSE 流式问答客户端（docs/06 §5.8）。
 * 事件序列：meta（检索完成立即下发）→ token* → ping(15s) → done / error。
 * EventSource 不支持 POST，故用 fetch + ReadableStream 手工解析。
 */

async function* parseSseStream(response, signal) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep
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
 * @param {object} payload QaAskRequest（question/session_no/kb_ids/mode/top_k/use_history）
 * @param {object} handlers { onMeta, onToken, onDone, onError }
 * @param {AbortController} controller 用于「停止生成」
 */
export async function streamAsk(payload, handlers, controller) {
  const token = localStorage.getItem('lexfin_token') || ''
  const resp = await fetch('/api/v1/qa/ask/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })

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
    for await (const { event, data } of parseSseStream(resp, controller.signal)) {
      if (event === 'meta') handlers.onMeta?.(data)
      else if (event === 'token') handlers.onToken?.(data.delta || '')
      else if (event === 'done') handlers.onDone?.(data)
      else if (event === 'error') handlers.onError?.(data)
      // ping：保活事件，无需处理
    }
  } catch (err) {
    if (err?.name !== 'AbortError') {
      handlers.onError?.({ code: -1, message: err?.message || '网络中断' })
    }
  }
}
