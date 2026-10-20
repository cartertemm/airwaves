"use strict";

const ANNOUNCE_DELAY_MS = 100;
const OUTPUT_LABELS = {local: "Server speakers", browsers: "This browser"};
const $ = (id) => document.getElementById(id);
const player = $("player");
let state = null;
let listening = false;
let playToken = 0;
let wantStationName = false;
const volumeWorks = (() => {
	// iPhone Safari ignores writes to the volume of media elements.
	const old = player.volume;
	player.volume = 0.5;
	const works = player.volume === 0.5;
	player.volume = old;
	return works;
})();

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

function setOptions(select, items, current) {
	// Rebuilding only on change keeps focus and the screen reader's place.
	const key = JSON.stringify(items);
	if (select.dataset.items === key) {
		return;
	}
	select.dataset.items = key;
	const chosen = select.value;
	select.replaceChildren(...items.map(({value, label}) => new Option(label, value)));
	for (const wanted of [chosen, current]) {
		if (items.some((item) => item.value === wanted)) {
			select.value = wanted;
			return;
		}
	}
}

function setValue(control, value, changed) {
	// A value from the radio waits in dataset.pending until it can be shown. The user's own change cancels it.
	if (changed) {
		control.dataset.pending = String(value);
	}
	const pending = control.dataset.pending;
	if (pending === undefined || document.activeElement === control) {
		return;
	}
	if (control.tagName !== "SELECT" || Array.from(control.options).some((option) => option.value === pending)) {
		control.value = pending;
		delete control.dataset.pending;
	}
}

function inBrowser() {
	return state !== null && state.output === "browsers";
}

function renderPlayback(updateVolume = false) {
	const playing = inBrowser() ? listening : !state.paused;
	const muted = inBrowser() ? player.muted : state.muted;
	$("play").setAttribute("aria-pressed", String(playing));
	$("mute").setAttribute("aria-pressed", String(muted));
	if (document.activeElement !== $("volume")) {
		$("volume").disabled = inBrowser() && !volumeWorks;
	}
	setValue($("volume"), inBrowser() ? Math.round(player.volume * 100) : state.volume, updateVolume);
}

function render(next) {
	const previous = state;
	state = next;
	const changed = (key) => previous === null || previous[key] !== next[key];
	const name = [next.frequency, next.station].filter(Boolean).join(" ");
	$("station").textContent = next.scanning ? "Scanning" : name;
	document.title = `${name} | SDR Tuner`;
	const tuned = previous !== null && !next.scanning && (changed("freq_mhz") || changed("band") || previous.scanning);
	if (tuned) {
		say($("message"), name);
		wantStationName = !next.station;
	} else if (wantStationName && next.station && !next.scanning) {
		say($("message"), next.station);
		wantStationName = false;
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
	setOptions($("band"), next.bands.map((band) => ({value: band.name, label: `${band.name}, ${band.min_mhz} to ${band.max_mhz} MHz`})), next.band);
	setValue($("band"), next.band, changed("band"));
	setValue($("frequency"), next.freq_mhz, changed("freq_mhz"));
	const programs = Object.entries(next.hd_programs).sort(([a], [b]) => a - b);
	const hdValue = next.hd_program === null ? "" : String(next.hd_program);
	setOptions($("hd"), [{value: "", label: "Analog"}, ...programs.map(([number, label]) => ({value: number, label: `HD${Number(number) + 1} ${label}`.trim()}))], hdValue);
	setValue($("hd"), hdValue, changed("hd_program"));
	setOptions($("preset"), next.presets.map((preset) => ({value: String(preset.number), label: `${preset.number}: ${preset.label}`})), "");
	setOptions($("output"), next.outputs.map((output) => ({value: output, label: OUTPUT_LABELS[output] || output})), next.output);
	setValue($("output"), next.output, changed("output"));
	if (previous && previous.output === "browsers" && next.output !== "browsers") {
		stopListening();
	}
	renderPlayback(changed("volume") || changed("output"));
}

function startListening() {
	listening = true;
	const token = ++playToken;
	// A new address each time, so the browser does not replay old audio from its cache.
	player.src = `stream?${Date.now()}`;
	player.play().catch((error) => {
		if (token !== playToken || error.name === "AbortError") {
			return;
		}
		stopListening();
		showError("The browser could not play the stream.");
	});
	renderPlayback();
}

function stopListening() {
	listening = false;
	playToken++;
	player.pause();
	player.removeAttribute("src");
	player.load();
	if (state) {
		renderPlayback();
	}
}

for (const id of ["band", "frequency", "hd", "output", "volume"]) {
	$(id).addEventListener("change", () => { delete $(id).dataset.pending; });
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
	if (state === null) {
		return;
	}
	if (inBrowser()) {
		listening ? stopListening() : startListening();
	} else {
		send("pause", {paused: !state.paused});
	}
});

$("mute").addEventListener("click", () => {
	if (state === null) {
		return;
	}
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

function streamStopped() {
	if (listening) {
		stopListening();
		showError("The stream stopped. Press Play to listen again.");
	}
}

player.addEventListener("error", streamStopped);
player.addEventListener("ended", streamStopped);

const events = new EventSource("events");
events.addEventListener("status", (event) => {
	$("connection").textContent = "";
	render(JSON.parse(event.data));
});
events.addEventListener("message", (event) => {
	const message = JSON.parse(event.data);
	if (message.error) {
		showError(message.text.replace(/^error: /, ""));
	} else if (message.text.startsWith("ALERT:")) {
		showError(message.text);
	} else {
		say($("message"), message.text);
	}
});
events.addEventListener("error", () => {
	const connection = $("connection");
	if (events.readyState === EventSource.CLOSED) {
		connection.textContent = "Connection to the radio closed. Reload the page.";
	} else if (connection.textContent === "") {
		connection.textContent = "Connection lost, reconnecting.";
	}
});
