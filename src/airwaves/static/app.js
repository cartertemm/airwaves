"use strict";

const ANNOUNCE_DELAY_MS = 100;
const OUTPUT_LABELS = {local: "Server speakers", browsers: "This browser"};
const $ = (id) => document.getElementById(id);
const player = $("player");
let state = null;
let listening = false;

function say(region, text) {
	// Clearing first makes screen readers repeat a message that is the same as the last one.
	region.textContent = "";
	setTimeout(() => { region.textContent = text; }, ANNOUNCE_DELAY_MS);
}

function showError(text) {
	say($("error"), text);
}

async function send(command, body = {}) {
	try {
		const response = await fetch(`api/${command}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
		if (!response.ok) {
			const reply = await response.json().catch(() => ({}));
			showError(reply.error || `The radio refused: ${response.status}.`);
		}
	} catch {
		showError("Could not reach the radio.");
	}
}

function setOptions(select, items) {
	// Rebuilding only on change keeps focus and the screen reader's place.
	const key = JSON.stringify(items);
	if (select.dataset.items === key) {
		return;
	}
	select.dataset.items = key;
	const chosen = select.value;
	select.replaceChildren(...items.map(({value, label}) => new Option(label, value)));
	if (items.some((item) => item.value === chosen)) {
		select.value = chosen;
	}
}

function setValue(control, value) {
	// Never change a control the user is on.
	if (document.activeElement !== control) {
		control.value = value;
	}
}

function inBrowser() {
	return state !== null && state.output === "browsers";
}

function renderPlayback() {
	const playing = inBrowser() ? listening : !state.paused;
	const muted = inBrowser() ? player.muted : state.muted;
	$("play").setAttribute("aria-pressed", String(playing));
	$("mute").setAttribute("aria-pressed", String(muted));
	setValue($("volume"), inBrowser() ? Math.round(player.volume * 100) : state.volume);
}

function render(next) {
	const previous = state;
	state = next;
	const name = [next.frequency, next.station].filter(Boolean).join(" ");
	$("station").textContent = next.scanning ? "Scanning" : name;
	document.title = `${name} | SDR Tuner`;
	if (previous && !next.scanning && (previous.frequency !== next.frequency || previous.station !== next.station || previous.scanning)) {
		say($("message"), name);
	}
	$("text").textContent = next.text;
	if (next.acars_active) {
		$("signal").textContent = `Messages: ${next.acars_count}`;
	} else if (next.hd_active) {
		$("signal").textContent = next.mer ? `MER ${next.mer[0].toFixed(1)} / ${next.mer[1].toFixed(1)} dB` : "";
	} else {
		$("signal").textContent = `Signal ${next.signal_db} dB`;
	}
	$("alert").hidden = !next.alert;
	$("alert").textContent = next.alert ? `Weather alert: ${next.alert}` : "";
	if (next.alert && (!previous || previous.alert !== next.alert)) {
		showError(`Weather alert: ${next.alert}`);
	}
	setOptions($("band"), next.bands.map((band) => ({value: band.name, label: `${band.name}, ${band.min_mhz} to ${band.max_mhz} MHz`})));
	setValue($("band"), next.band);
	setValue($("frequency"), next.freq_mhz);
	const programs = Object.entries(next.hd_programs).sort(([a], [b]) => a - b);
	setOptions($("hd"), [{value: "", label: "Analog"}, ...programs.map(([number, label]) => ({value: number, label: `HD${Number(number) + 1} ${label}`.trim()}))]);
	setValue($("hd"), next.hd_program === null ? "" : String(next.hd_program));
	setOptions($("preset"), next.presets.map((preset) => ({value: String(preset.number), label: `${preset.number}: ${preset.label}`})));
	setOptions($("output"), next.outputs.map((output) => ({value: output, label: OUTPUT_LABELS[output] || output})));
	setValue($("output"), next.output);
	if (previous && previous.output === "browsers" && next.output !== "browsers") {
		stopListening();
	}
	renderPlayback();
}

function startListening() {
	listening = true;
	// A new address each time, so the browser does not replay old audio from its cache.
	player.src = `stream?${Date.now()}`;
	player.play().catch(() => {
		stopListening();
		showError("The browser could not play the stream.");
	});
	renderPlayback();
}

function stopListening() {
	listening = false;
	player.pause();
	player.removeAttribute("src");
	player.load();
	if (state) {
		renderPlayback();
	}
}

function submit(id, handler) {
	$(id).addEventListener("submit", (event) => {
		event.preventDefault();
		handler();
	});
}

submit("tune-form", () => send("tune", {mhz: Number($("frequency").value)}));
submit("band-form", () => send("band", {name: $("band").value}));
submit("hd-form", () => send("hd", {program: $("hd").value === "" ? null : Number($("hd").value)}));
submit("preset-form", () => {
	if ($("preset").value === "") {
		showError("No presets yet. Save the current station first.");
		return;
	}
	send("preset", {number: Number($("preset").value)});
});
submit("output-form", () => send("output", {target: $("output").value}));

for (const button of document.querySelectorAll(".move")) {
	button.addEventListener("click", () => send(button.dataset.command, {direction: Number(button.dataset.direction)}));
}

$("save-preset").addEventListener("click", () => send("save_preset"));

$("find-speakers").addEventListener("click", () => {
	say($("message"), "Looking for speakers. This takes about 5 seconds.");
	send("find_speakers");
});

$("play").addEventListener("click", () => {
	if (inBrowser()) {
		listening ? stopListening() : startListening();
	} else {
		send("pause", {paused: !state.paused});
	}
});

$("mute").addEventListener("click", () => {
	if (inBrowser()) {
		player.muted = !player.muted;
		renderPlayback();
	} else {
		send("mute", {muted: !state.muted});
	}
});

$("volume").addEventListener("change", () => {
	const percent = Number($("volume").value);
	if (inBrowser()) {
		player.volume = percent / 100;
	} else {
		send("volume", {percent});
	}
});

player.addEventListener("error", () => {
	if (listening) {
		stopListening();
		showError("The stream stopped. Press Play to listen again.");
	}
});

const events = new EventSource("events");
events.addEventListener("status", (event) => {
	$("connection").textContent = "";
	render(JSON.parse(event.data));
});
events.addEventListener("message", (event) => {
	const message = JSON.parse(event.data);
	if (message.error) {
		showError(message.text.replace(/^error: /, ""));
	} else {
		say($("message"), message.text);
	}
});
events.addEventListener("error", () => {
	$("connection").textContent = "Connection lost, reconnecting.";
});
