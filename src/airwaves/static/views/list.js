// Each entry is a real button, so touch screen readers need nothing special.
// The container has role="application" so NVDA and JAWS pass arrow keys
// through. Only the highlighted button is in the tab order, so Tab enters and
// leaves the list in one press.

import { el, mount } from 'audiogame-utils'

const PAGE = 10

export function keyboardList({ label, items, onChoose, onRemove = null, onHighlight = null, emptyText, startId = null, startIndex = null }) {
	const start = items.findIndex(item => item.id === startId)
	const fallback = startIndex === null ? Math.max(0, items.findIndex(item => item.current)) : Math.max(0, Math.min(items.length - 1, startIndex))
	let index = start >= 0 ? start : fallback
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
		onHighlight?.()
		if (focus) buttons[index].focus()
	}

	// Out of the tab order: keyboard users press Delete instead.
	function removeButton(item) {
		return el('button', { type: 'button', class: 'list-remove', text: 'Clear', 'aria-label': `Clear ${item.label}`, tabindex: '-1', onClick: () => onRemove(item.id) })
	}

	function onKeyDown(event) {
		if (buttons.length === 0 || event.ctrlKey || event.altKey || event.metaKey) return
		const moves = { ArrowDown: index + 1, ArrowUp: index - 1, PageDown: index + PAGE, PageUp: index - PAGE, Home: 0, End: buttons.length - 1 }
		if (event.key in moves) highlight(moves[event.key])
		else if (onRemove && (event.key === 'Delete' || event.key === 'Backspace')) onRemove(items[index].id)
		else return
		event.preventDefault()
	}

	const node = el(
		'div',
		{ role: 'application', 'aria-label': label, class: 'list', onKeydown: onKeyDown },
		buttons.length > 0 ? el('ul', {}, ...buttons.map((button, position) => el('li', {}, button, ...(onRemove ? [removeButton(items[position])] : [])))) : el('p', { class: 'empty', text: emptyText }),
	)
	return { node, isEmpty: buttons.length === 0, focus: () => buttons[index]?.focus(), selectedId: () => items[index]?.id ?? null, selectedIndex: () => index }
}

export function listScreen(root, { radio, describe, onDone }) {
	const first = describe(radio)
	const holder = el('div')
	const actionsHolder = el('div', { class: 'actions' })
	const close = el('button', { type: 'button', text: 'Close', onClick: onDone })
	let shown = null
	let list = null
	let actions = []

	function draw() {
		const view = describe(radio)
		const key = JSON.stringify(view.items)
		if (key === shown) return
		const focusList = list === null || list.node.contains(document.activeElement)
		const startId = list?.selectedId() ?? null
		const startIndex = list?.selectedIndex() ?? null
		shown = key
		list = keyboardList({
			label: view.title,
			items: view.items,
			startId,
			startIndex,
			emptyText: view.emptyText,
			// Back to the front panel first: screen readers cut speech off when focus moves.
			onChoose: id => {
				onDone()
				view.onChoose(id)
			},
			onRemove: view.onRemove,
			onHighlight: relabel,
		})
		const focusedAction = [...actionsHolder.children].indexOf(document.activeElement)
		holder.replaceChildren(list.node)
		actions = view.actions ?? []
		actionsHolder.replaceChildren(...actions.map(action => el('button', { type: 'button', class: 'action', text: actionText(action), onClick: () => action.onClick(list.selectedId()) })))
		const sameAction = actionsHolder.children[focusedAction]
		if (sameAction) sameAction.focus()
		else if (focusList || focusedAction >= 0) (list.isEmpty ? close : list).focus()
	}

	function actionText(action) {
		return typeof action.text === 'function' ? action.text(list.selectedId()) : action.text
	}

	function relabel() {
		actions.forEach((action, position) => {
			const button = actionsHolder.children[position]
			if (button) button.textContent = actionText(action)
		})
	}

	mount(root, [
		el(
			'main',
			{ class: 'sheet' },
			el('div', { class: 'sheet-head' }, el('h1', { text: first.title }), close),
			holder,
			actionsHolder,
		),
	])
	draw()
	return radio.onChange(draw)
}
