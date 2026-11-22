'use strict';
'require view';
'require form';
'require poll';
'require rpc';
'require ui';
'require view/adguardhome/status as status';

var callInterfaces = rpc.declare({
	object: 'luci.adguardhome',
	method: 'getInterfaces',
	expect: { '': {} },
	reject: true
});

var callCoreUpdate = rpc.declare({
	object: 'luci.adguardhome',
	method: 'getCoreUpdate',
	expect: { '': {} },
	reject: true
});

var callStartCoreUpdate = rpc.declare({
	object: 'luci.adguardhome',
	method: 'startCoreUpdate',
	params: [ 'force' ],
	expect: { '': {} },
	reject: true
});

function localizeUpdateLog(log) {
	return log.split('\n').map(function(line) {
		if (!line)
			return '';
		var translated = _(line, 'Core update log');
		var separator = line.indexOf(': ');
		if (translated !== line || separator === -1)
			return translated;

		var label = line.slice(0, separator);
		var value = line.slice(separator + 2);
		if (label === 'Current AdGuard Home version' && value === 'unknown')
			value = _('unknown', 'Core update log');
		return _(label, 'Core update log') + ': ' + value;
	}).join('\n');
}

return view.extend({
	handleSaveApply: function(ev, mode) {
		var target = {
			mode: this.redirectOption.formvalue('AdGuardHome') || 'none',
			enabled: this.enabledOption.formvalue('AdGuardHome') === '1'
		};
		this.sharedStatus.beginSwitch(target);
		return this.handleSave(ev).then(function() {
			ui.changes.apply(mode == '0');
		}).catch(function(error) {
			this.sharedStatus.cancelSwitch();
			throw error;
		}.bind(this));
	},

	load: function() {
		return callInterfaces().catch(function() { return { interfaces: [] }; });
	},

	render: function(data) {
		let m, s, o;
		var self = this;
		var interfaces = data.interfaces || [];

		m = new form.Map('AdGuardHome');

		s = m.section(
			form.TypedSection,
			'AdGuardHome',
			_('Basic Settings')
		);

		s.anonymous = true;
		s.addremove = false;

		o = s.option(
			form.Flag,
			'enabled',
			_('Enable')
		);
		this.enabledOption = o;
		o.default = '0';
		o.rmempty = false;

		o = s.option(
			form.Value,
			'httpport',
			_('Browser management port')
		);
		o.datatype = 'port';
		o.placeholder = '3000';
		o.default = '3000';
		o.rmempty = false;

		o = s.option(
			form.ListValue,
			'redirect',
			_('DNS handling mode')
		);

		this.redirectOption = o;
		o.value('none', _('Do not handle DNS'));
		o.value('redirect', _('Forward port 53 requests through the firewall (recommended)'));
		o.value('dnsmasq-upstream', _('Run as dnsmasq upstream server'));
		o.value('exchange', _('Use port 53 instead of dnsmasq'));

		o.default = 'none';
		o.rmempty = false;

		o = s.option(
			form.DynamicList,
			'wan_ifname',
			_('Network devices excluded from forwarding'),
			_('DNS requests arriving on these network devices are not forwarded to AdGuardHome')
		);
		o.depends('redirect', 'redirect');
		o.retain = true;
		o.datatype = 'string';
		o.rmempty = true;
		interfaces.filter(function(name) { return name !== 'lo'; }).forEach(function(name) {
			o.value(name, name);
		});

		o = s.option(
			form.Value,
			'binpath',
			_('Bin Path')
		);
		o.default = '/usr/bin/AdGuardHome/AdGuardHome';
		o.rmempty = false;

		o = s.option(
			form.Value,
			'configpath',
			_('Config Path')
		);
		o.default = '/etc/AdGuardHome.yaml';
		o.rmempty = false;

		o = s.option(
			form.Value,
			'workdir',
			_('Work dir')
		);
		o.default = '/usr/bin/AdGuardHome';
		o.rmempty = false;


		return m.render().then(function(node) {
			var sharedStatus = status.render();
			self.sharedStatus = sharedStatus;

			var updateButton = E('button', {
				'class': 'btn cbi-button cbi-button-apply', 'type': 'button'
			}, _('Update core version'));
			var forceButton = E('button', {
				'class': 'btn cbi-button', 'type': 'button'
			}, _('Force update'));
			var updateMessage = E('span', {}, '');
			var reverseLog = E('input', { 'type': 'checkbox' });
			var updateLog = E('textarea', {
				'class': 'cbi-input-textarea agh-update-log', 'rows': 8, 'readonly': 'readonly',
				'style': 'display:none;'
			});
			var logOptions = E('label', { 'class': 'agh-update-options', 'style': 'display:none;' }, [
				reverseLog, E('span', {}, _('reverse'))
			]);
			var updatePanel = E('div', { 'class': 'cbi-value' }, [
				E('div', { 'class': 'cbi-value-title' }, _('Upgrade Core')),
				E('div', { 'class': 'cbi-value-field' }, E('div', { 'class': 'agh-update-content' }, [
					E('div', { 'class': 'agh-toolbar' }, [updateButton, forceButton, updateMessage]),
					logOptions, updateLog
				]))
			]);
			var lastLog = '';
			var starting = false;
			var statusRequest = 0;
			var activeUpdate = false;
			var updateFinishedHere = false;
			var messages = {
				current: _('Already up to date'),
				finished: _('Updated'),
				start_failed: _('Core installed, service failed to start'),
				failure: _('Update failed'),
				restore_start_failed: _('Service failed to start during restore'),
				backup_failed: _('Backup failed'),
				restore_failed: _('Restore failed'),
				delete_failed: _('Delete failed')
			};

			function setBusy(busy) {
				updateButton.disabled = forceButton.disabled = !!(busy || m.readonly);
			}
			setBusy(false);

			function showLog() {
				updateLog.value = reverseLog.checked ? lastLog.split('\n').reverse().join('\n') : lastLog;
			}
			reverseLog.addEventListener('change', showLog);

			function showUpdateStatus(result) {
				var state = result.state || 'idle';
				if (state === 'running')
					activeUpdate = true;
				else if (activeUpdate && state !== 'idle') {
					activeUpdate = false;
					updateFinishedHere = true;
					sharedStatus.refresh();
				}

				setBusy(state === 'running');
				if (state === 'running' || updateFinishedHere) {
					updateMessage.textContent = messages[state] || '';
					lastLog = localizeUpdateLog(result.log || '');
					logOptions.style.display = lastLog ? 'inline-flex' : 'none';
					updateLog.style.display = lastLog ? 'block' : 'none';
					showLog();
				} else {
					updateMessage.textContent = '';
					lastLog = '';
					logOptions.style.display = updateLog.style.display = 'none';
				}
			}

			function refreshUpdate() {
				if (starting)
					return;
				var request = ++statusRequest;
				return callCoreUpdate().then(function(result) {
					if (request === statusRequest)
						showUpdateStatus(result);
				}).catch(function() {
					if (request === statusRequest)
						updateMessage.textContent = _('Update status unavailable');
				});
			}

			function startUpdate(force) {
				starting = true;
				statusRequest++;
				activeUpdate = true;
				updateFinishedHere = false;
				setBusy(true);
				updateMessage.textContent = _('Check...');
				lastLog = '';
				showLog();
				updateLog.style.display = logOptions.style.display = 'none';
				callStartCoreUpdate(force).then(function(result) {
					starting = false;
					if (!result.started && result.reason !== 'busy')
						throw new Error();
					if (!result.started)
						updateMessage.textContent = '';
					return refreshUpdate();
				}).catch(function() {
					starting = false;
					activeUpdate = false;
					setBusy(false);
					updateMessage.textContent = _('Unable to start update');
				});
			}

			updateButton.addEventListener('click', function() { startUpdate(false); });
			forceButton.addEventListener('click', function() { startUpdate(true); });
			poll.add(refreshUpdate, 3);
			var settingsCard = node.querySelector('.cbi-section');
			settingsCard.classList.add('agh-compact-card', 'agh-base-card');
			var settingsFields = settingsCard.querySelector('.cbi-section-node') || settingsCard;
			settingsFields.appendChild(updatePanel);
			node.insertBefore(sharedStatus.node, node.firstChild);
			node.insertBefore(E('link', {
				'rel': 'stylesheet', 'href': L.resource('view/adguardhome/compact.css')
			}), node.firstChild);

			var portInput = node.querySelector('[data-name="httpport"] input');
			var portField = node.querySelector('[data-name="httpport"] .cbi-value-field');
			if (portInput && portField) {
				var webLink = E('input', {
					'type': 'button',
					'style': 'width:210px;border-color:Teal;text-align:center;font-weight:bold;color:#337ab7;background:#ffc800;',
					'target': '_blank',
					'value': _('AdGuardHome Web')
				});
				var linkWrap = E('div', { 'style': 'margin-top:0.35rem;' }, webLink);
				var host = window.location.hostname;
				if (host.indexOf(':') >= 0 && host.charAt(0) !== '[')
					host = '[' + host + ']';

				function updateWebLink() {
					var port = portInput.value.trim();
					var valid = /^[0-9]+$/.test(port) && +port >= 1 && +port <= 65535;
					webLink.value = _('AdGuardHome Web') + ': ' + port;
					webLink.onclick = valid ? function() {
						window.open('http://' + host + ':' + port + '/');
					} : null;
					webLink.style.display = valid ? 'inline-block' : 'none';
				}

				portField.appendChild(linkWrap);
				portInput.addEventListener('input', updateWebLink);
				updateWebLink();
			}

			return node;
		});
	}
});
