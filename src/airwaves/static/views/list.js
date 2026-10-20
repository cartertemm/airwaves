// A keyboard list for presets, bands, HD programs, and outputs.
//
// Each entry is a real button, so touch screen readers need nothing special.
// The container has role="application" so NVDA and JAWS pass arrow keys
// through. Only the highlighted button is in the tab order, so Tab enters and
// leaves the list in one press.

import { el, mount } from 'audiogame-utils'

const PAGE = 10

/** items: [{ id, label, current }]. Callbacks get the item id. onRemove is optional. startId picks the highlighted item, otherwise the current one. */
export function keyboardList({ label, items, onChoose, onRemove = null, emptyText, startId = null }) {
	const start = items.findIndex(item => item.id === startId)
	let index = start >= 0 ? start : Math.max(0, items.findIndex(item => item.current))
	const buttons = items.map((item, position) =>
		el('button', {
			type: 'button',
			class: 'list-item',
			text: item.label,
			tabindex: position === index ? '0' : '-1',
			...(item.current ? { 'aria-current': 'true' } : {}),
			onClick: () => onChoose(item.id),
			onFocus: () => highlight(position, false),
		}),
	)

	function highlight(next, focus = true) {
		if (buttons.length === 0) return
		buttons[index].setAttribute('tabindex', '-1')
		index = Math.max(0, Math.min(buttons.length - 1, next))
		buttons[index].setAttribute('tabindex', '0')
		if (focus) buttons[index].focus()
	}

	function onKeyDown(event) {
		if (buttons.length === 0 || event.ctrlKey || event.altKey || event.metaKey) return
		const moves = { ArrowDown: index + 1, ArrowUp: index - 1, PageDown: index + PAGE, PageUp: index - PAGE, Home: 0, End: buttons.length - 1 }
		if (event.key in moves) highlight(moves[event.key])
		else if (onRemove && event.key === 'Delete') onRemove(items[index].id)
		else return
		event.preventDefault()
	}

	const node = el(
		'div',
		{ role: 'application', 'aria-label': label, class: 'list', onKeydown: onKeyDown },
		buttons.length > 0 ? el('ul', {}, ...buttons.map(button => el('li', {}, button))) : el('p', { class: 'empty', text: emptyText }),
	)
	return { node, isEmpty: buttons.length === 0, focus: () => buttons[index]?.focus(), selectedId: () => items[index]?.id ?? null }
}

/**
 * A sheet with a heading, a keyboard list, optional action buttons, and Close.
 * props: { radio, describe, onDone }. describe(radio) returns
 * { title, items, onChoose(id), onRemove?(id), emptyText, actions?: [{ text, onClick }] }.
 * It is called again whenever the radio changes. Only the list is rebuilt, and
 * only when its items change, so focus on the other buttons stays put.
 */
export function listScreen(root, { radio, describe, onDone }) {
	const first = describe(radio)
	const holder = el('div')
	const close = el('button', { type: 'button', text: 'Close', onClick: onDone })
	let shown = null
	let list = null

	function draw() {
		const view = describe(radio)
		const key = JSON.stringify(view.items)
		if (key === shown) return
		const focusList = list === null || list.node.contains(document.activeElement)
		const startId = list?.selectedId() ?? null
		shown = key
		list = keyboardList({
			label: view.title,
			items: view.items,
			startId,
			emptyText: view.emptyText,
			// Back to the front panel first: screen readers cut speech off when focus moves.
			onChoose: id => {
				onDone()
				view.onChoose(id)
			},
			onRemove: view.onRemove,
		})
		holder.replaceChildren(list.node)
		if (focusList) (list.isEmpty ? close : list).focus()
	}

	mount(root, [
		el(
			'main',
			{ class: 'sheet' },
			el('div', { class: 'sheet-head' }, el('h1', { text: first.title }), close),
			holder,
			...(first.actions ?? []).map(action => el('button', { type: 'button', class: 'action', text: action.text, onClick: action.onClick })),
		),
	])
	draw()
	return radio.onChange(draw)
}
