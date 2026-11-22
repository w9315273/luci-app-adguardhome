'use strict';
'require baseclass';
'require poll';
'require rpc';

var callCoreInfo = rpc.declare({
	object: 'luci.adguardhome',
	method: 'getCoreInfo',
	expect: { '': {} },
	reject: true
});

var callServiceList = rpc.declare({
	object: 'service',
	method: 'list',
	params: [ 'name', 'verbose' ],
	expect: { '': {} },
	reject: true
});

var callRedirectStatus = rpc.declare({
	object: 'luci.adguardhome',
	method: 'getRedirectStatus',
	expect: { '': {} },
	reject: true
});

function modeLabel(mode) {
	return {
		none: _('Do not handle DNS'),
		'dnsmasq-upstream': _('Run as dnsmasq upstream server'),
		redirect: _('Forward port 53 requests through the firewall'),
		exchange: _('Use port 53 instead of dnsmasq')
	}[mode] || _('Status unavailable');
}

function coreIsRunning(services, binpath) {
	var instances = services.AdGuardHome && services.AdGuardHome.instances;
	if (!instances)
		return false;

	return Object.keys(instances).some(function(name) {
		var instance = instances[name];
		return instance.running === true && Array.isArray(instance.command) && instance.command[0] === binpath;
	});
}

return baseclass.extend({
	render: function() {
		var badgeStyle = 'display:inline-flex;align-items:center;padding:0.4em 0.8em;' +
			'border:1px solid;border-radius:999px;font-weight:600;line-height:1.4;';
		var coreLabel = _('Core', 'AdGuard Home status');
		var coreBadge = E('span', { 'style': badgeStyle }, _('Collecting data...'));
		var serviceBadge = E('span', { 'style': badgeStyle }, _('Collecting data...'));
		var redirectBadge = E('span', { 'style': badgeStyle }, _('Collecting data...'));
		var node = E('div', { 'class': 'cbi-section' }, [
			E('div', { 'style': 'display:flex;flex-wrap:wrap;gap:0.6em;padding:0.6em;' }, [
				coreBadge, serviceBadge, redirectBadge
			])
		]);

		function setBadge(badge, label, state) {
			badge.textContent = label;
			badge.style.backgroundColor = state === 'pending' ? '#fef3c7' : state === true ? '#dcfce7' : state === false ? '#fee2e2' : '#e5e7eb';
			badge.style.color = state === 'pending' ? '#92400e' : state === true ? '#14532d' : state === false ? '#7f1d1d' : '#374151';
			badge.style.borderColor = state === 'pending' ? '#fcd34d' : state === true ? '#86efac' : state === false ? '#fca5a5' : '#d1d5db';
		}

		function refreshCore() {
			return callCoreInfo().then(function(info) {
				if (!info.core_exists)
					setBadge(coreBadge, coreLabel + ': ' + _('no core'), false);
				else if (!info.version)
					setBadge(coreBadge, coreLabel + ': ' + _('core error'), false);
				else if (!info.config_exists)
					setBadge(coreBadge, coreLabel + ': ' + info.version + ' (' + _('no config') + ')', false);
				else
					setBadge(coreBadge, coreLabel + ': ' + info.version, true);
			}).catch(function() {
				setBadge(coreBadge, coreLabel + ': ' + _('Status unavailable'), null);
			});
		}

		var storageKey = 'adguardhome.pendingSwitch';
		var pending = null;
		var generation = 0;
		var stable = 0;
		var nextRefresh = 0;
		var inFlight = null;
		try {
			var saved = JSON.parse(sessionStorage.getItem(storageKey));
			if (saved && typeof saved.mode === 'string' && typeof saved.enabled === 'boolean' &&
				typeof saved.started === 'number')
				pending = saved;
		} catch (e) {}

		function remember() {
			try {
				if (pending)
					sessionStorage.setItem(storageKey, JSON.stringify(pending));
				else
					sessionStorage.removeItem(storageKey);
			} catch (e) {}
		}

		function showPending(running) {
			var label = Date.now() - pending.started >= 30000
				? _('Switch not completed; check the log') : _('Switching');
			if (typeof running === 'boolean')
				setBadge(serviceBadge, running ? _('RUNNING') : _('NOT RUNNING'), running);
			else
				setBadge(serviceBadge, _('Checking service…'), 'pending');
			setBadge(redirectBadge, label, 'pending');
		}

		function beginSwitch(target) {
			generation++;
			stable = 0;
			nextRefresh = 0;
			pending = { mode: target.mode, enabled: target.enabled, started: Date.now() };
			remember();
			showPending();
		}

		function cancelSwitch() {
			generation++;
			pending = null;
			stable = 0;
			nextRefresh = 0;
			remember();
			return refreshStatus();
		}

		function matches(info, running, target) {
			return !info.busy && info.mode === target.mode && info.enabled === target.enabled &&
				info.applied_enabled === target.enabled && running === target.enabled &&
				(!target.enabled || info.applied_mode === target.mode) &&
				info.redirected === (target.enabled && target.mode !== 'none');
		}

		function refreshStatus() {
			if (inFlight)
				return inFlight;
			var currentGeneration = generation;
			var requestedAt = Date.now();
			inFlight = Promise.all([callRedirectStatus(), callServiceList('AdGuardHome', true)]).then(function(results) {
				if (currentGeneration !== generation)
					return;
				var info = results[0];
				var running = coreIsRunning(results[1], info.binpath);
				// Recover switching feedback after navigation or an apply from another page.
				if (!pending && (info.busy || info.mode !== info.applied_mode || info.enabled !== info.applied_enabled))
					beginSwitch(info);
				if (pending) {
					stable = matches(info, running, pending) ? stable + 1 : 0;
					// Two consecutive samples avoid declaring a short-lived process healthy.
					if (stable < 2) {
						showPending(running);
						return;
					}
					pending = null;
					remember();
				}
				setBadge(serviceBadge, running ? _('RUNNING') : _('NOT RUNNING'), running);
				var active = info.redirected && running && info.mode === info.applied_mode;
				var label = modeLabel(info.mode);
				if (!info.enabled)
					label += ' (' + _('Disabled') + ')';
				else if (info.mode !== 'none' && !active)
					label += ' (' + _('Not redirect') + ')';
				setBadge(redirectBadge, label,
					!info.enabled || info.mode === 'none' ? null : active);
			}).catch(function() {
				if (currentGeneration !== generation)
					return;
				stable = 0;
				if (pending) {
					showPending();
					setBadge(serviceBadge, _('Status unavailable'), null);
					setBadge(redirectBadge, _('Unable to read switch status') + ' (' + modeLabel(pending.mode) + ')', null);
				} else {
					setBadge(serviceBadge, _('Status unavailable'), null);
					setBadge(redirectBadge, _('Status unavailable'), null);
				}
			}).then(function() {
				nextRefresh = requestedAt + (pending ? 1000 : 3000);
				inFlight = null;
			});
			return inFlight;
		}

		if (pending)
			showPending();
		refreshCore();
		refreshStatus();
		poll.add(function() {
			if (Date.now() >= nextRefresh)
				return refreshStatus();
		}, 1);

		return { node: node, refresh: function() {
			return Promise.all([refreshCore(), refreshStatus()]);
		}, beginSwitch: beginSwitch, cancelSwitch: cancelSwitch };
	}
});
