// Talks to the radio: commands as JSON POSTs, status and messages as server-sent events.

export function createApi({ fetchFn = (...args) => globalThis.fetch(...args), EventSourceClass = globalThis.EventSource } = {}) {
	return {
		/** Sends a command. Rejects with an Error whose message can be spoken. */
		async post(name, body = {}) {
			let response
			try {
				response = await fetchFn(`api/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
			} catch {
				throw new Error("Can't reach the radio.")
			}
			if (!response.ok) {
				const reply = await response.json().catch(() => ({}))
				throw new Error(reply.error ?? `The radio refused the command: ${response.status}.`)
			}
		},

		/** onConnection gets 'open', 'lost' (the browser is reconnecting), or 'closed'. Returns a function that stops listening. */
		listen({ onStatus, onMessage, onConnection }) {
			const events = new EventSourceClass('events')
			events.addEventListener('status', event => {
				onConnection('open')
				onStatus(JSON.parse(event.data))
			})
			events.addEventListener('message', event => onMessage(JSON.parse(event.data)))
			events.addEventListener('error', () => onConnection(events.readyState === EventSourceClass.CLOSED ? 'closed' : 'lost'))
			return () => events.close()
		},
	}
}
