'use strict';
'require view';
'require poll';
'require rpc';
'require ui';
'require view/adguardhome/status as status';

var callHistory = rpc.declare({
	object: 'luci.adguardhome',
	method: 'getBackupHistory',
	expect: { '': {} },
	reject: true
});

var callBackupAction = rpc.declare({
	object: 'luci.adguardhome',
	method: 'coreBackupAction',
	params: [ 'action', 'backup_id' ],
	expect: { '': {} },
	reject: true
});

return view.extend({
	handleSave: null,
	handleSaveApply: null,
	handleReset: null,

	load: function() {
		return callHistory().catch(function() { return null; });
	},

	render: function(initial) {
		var sharedStatus = status.render();
		var readonly = !L.hasViewPermission();
		var history = null;
		var previousRows = '';
		var requestNumber = 0;
		var starting = false;
		var refreshingCore = false;
		var actionError = '';
		var busyMessage = _('Another core task is running. This operation did not start. Try again when it finishes.');
		var entryButtons = [];
		var formatter = new Intl.DateTimeFormat(document.documentElement.lang || undefined, {
			year: 'numeric', month: '2-digit', day: '2-digit',
			hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
		});
		var sourceLabels = {
			update: _('Before core update'),
			manual: _('Manual backup'),
			legacy: _('Legacy backup')
		};
		var errorLabels = {
			restore_start_failed: _('Service failed to start during restore'),
			rollback_start_failed: _('The previous files were restored, but the original service failed to start.', 'Core update log'),
			rollback_failed: _('Rollback incomplete. The previous files are kept for the next attempt.', 'Core update log'),
			backup_failed: _('Backup failed'),
			restore_failed: _('Restore failed'),
			delete_failed: _('Delete failed')
		};
		var components = {
			core: {
				create: _('Create core backup'),
				restore: _('Restore core'),
				missing: _('No core is installed.'),
				question: _('Restore the core from this backup?')
			},
			config: {
				create: _('Create configuration backup'),
				restore: _('Restore configuration'),
				missing: _('The YAML configuration file is missing.'),
				question: _('Restore the YAML configuration from this backup?')
			},
			both: {
				restore: _('Restore both'),
				question: _('Restore the core and YAML configuration together from this backup?')
			}
		};
		function createButton(component) {
			var action = 'backup-' + component;
			return E('button', {
				'class': 'btn cbi-button cbi-button-apply', 'type': 'button', 'data-action': action,
				'click': function() { run(action, ''); }
			}, components[component].create);
		}

		var createCore = createButton('core');
		var createConfig = createButton('config');
		var message = E('span', { 'class': 'agh-backup-status', 'role': 'status' });
		var list = E('ol', { 'class': 'agh-backup-timeline' });
		var empty = E('p', { 'class': 'agh-backup-empty' }, _('No backups yet.'));

		function updateControls() {
			var writable = !readonly && history != null;
			var busy = starting || (history && history.state === 'running');
			function setControl(button, available) {
				button.disabled = !available || busy;
				button.classList.toggle('agh-backup-unavailable', !available);
			}
			setControl(createCore, writable && history.core_exists);
			setControl(createConfig, writable && history.config_exists);
			createCore.title = history && !history.core_exists ? components.core.missing : '';
			createConfig.title = history && !history.config_exists ? components.config.missing : '';
			entryButtons.forEach(function(button) {
				setControl(button, writable);
			});
		}

		function confirmAction(action, id, label, description, question) {
			var buttonClass = action === 'delete' ? 'cbi-button-remove' : 'cbi-button-apply';
			ui.showModal(label, [
				E('p', {}, [description]),
				E('p', {}, [question]),
				E('div', { 'class': 'right' }, [
					E('button', { 'class': 'btn', 'type': 'button', 'click': ui.hideModal }, _('Cancel')), ' ',
					E('button', { 'class': 'btn cbi-button ' + buttonClass, 'type': 'button', 'click': function() {
						ui.hideModal();
						run(action, id);
					} }, label)
				])
			]);
		}

		function restoreButton(entry, timeLabel, component) {
			var labels = components[component];
			var action = 'restore-' + component;
			var button = E('button', {
				'class': 'btn cbi-button cbi-button-action', 'type': 'button', 'data-action': action,
				'click': function() {
					var description = component !== 'config' && entry.version ? timeLabel + ' / ' + entry.version : timeLabel;
					var restart = component === 'config' ? _('The service will restart if enabled and the core is installed.') :
						_('The service will restart if enabled.');
					confirmAction(action, entry.id, labels.restore, description, labels.question + ' ' + restart);
				}
			}, labels.restore);
			entryButtons.push(button);
			return button;
		}

		function renderEntry(entry) {
			var date = new Date(entry.created * 1000);
			var hasDate = entry.created > 0 && Number.isFinite(date.getTime());
			var timeLabel = hasDate ? formatter.format(date) : _('Time unavailable');
			var contents = [];
			var actions = [];
			if (entry.has_core) {
				contents.push(_('Core', 'AdGuard Home status') + (entry.version ? ' ' + entry.version : ''));
				actions.push(restoreButton(entry, timeLabel, 'core'));
			} else if (entry.damaged_core)
				contents.push(_('Damaged core'));
			if (entry.has_config) {
				contents.push('YAML');
				actions.push(restoreButton(entry, timeLabel, 'config'));
			}
			if (entry.has_core && entry.has_config)
				actions.push(restoreButton(entry, timeLabel, 'both'));
			var deleteButton = E('button', {
				'class': 'btn cbi-button cbi-button-remove', 'type': 'button', 'data-action': 'delete',
				'click': function() {
					var description = [timeLabel, sourceLabels[entry.source]].concat(contents).join(' / ');
					confirmAction('delete', entry.id, _('Delete backup'), description,
						_('Permanently delete this backup from the router?'));
				}
			}, _('Delete', 'AdGuard Home backup'));
			entryButtons.push(deleteButton);
			return E('li', { 'class': 'agh-backup-entry agh-backup-row' }, [
				E('div', { 'class': 'agh-backup-info' }, [
					E('div', { 'class': 'agh-backup-entry-header' }, [
						E('time', hasDate ? { 'datetime': date.toISOString() } : {}, [timeLabel]),
						E('span', { 'class': 'agh-backup-source' }, [sourceLabels[entry.source]])
					]),
					E('div', { 'class': 'agh-backup-files' }, contents.map(function(file) {
						return E('span', { 'class': 'agh-backup-file' }, [file]);
					}))
				]),
				...actions, deleteButton
			]);
		}

		function show(result) {
			var wasRunning = history && history.state === 'running';
			history = result && Array.isArray(result.entries) ? result : null;
			if (history) {
				var entries = result.entries;
				var key = JSON.stringify(entries);
				// 保留轮询间隔内的键盘焦点, 仅在记录改变时重建时间线.
				if (previousRows !== key) {
					previousRows = key;
					entryButtons = [];
					list.replaceChildren(...entries.map(renderEntry));
				}
				empty.hidden = entries.length > 0;
				var text = errorLabels[result.state] || '';
				if (result.detail)
					text += (text ? ': ' : '') + _(result.detail, 'Core update log');
				if (actionError)
					text = actionError + (text ? ' ' + text : '');
				for (var warning of result.warnings || [])
					text += (text ? ' ' : '') + _(warning, 'Core update log');
				if (result.state !== 'running') {
					if (!result.core_exists && result.detail !== 'YAML validation skipped: no core is installed.')
						text += (text ? ' ' : '') + _('No core is installed. YAML backups and restores will skip validation.');
					if (!result.config_exists)
						text += (text ? ' ' : '') + components.config.missing;
				}
				message.textContent = text;
				if ((wasRunning || refreshingCore) && result.state !== 'running') {
					refreshingCore = false;
					sharedStatus.refresh();
				}
			} else {
				empty.hidden = true;
				message.textContent = _('Unable to read backup history');
			}
			updateControls();
		}

		function refresh() {
			if (starting)
				return;
			var request = ++requestNumber;
			return callHistory().then(function(result) {
				if (request === requestNumber)
					show(result);
			}).catch(function() {
				if (request === requestNumber)
					show(null);
			});
		}

		function run(action, id) {
			if (readonly || !history)
				return;
			if (starting || history.state === 'running') {
				actionError = busyMessage;
				message.textContent = actionError;
				return;
			}
			starting = true;
			requestNumber++;
			actionError = '';
			message.textContent = '';
			updateControls();
			return callBackupAction(action, id).then(function(result) {
				if (!result.started) {
					if (result.reason === 'busy')
						actionError = busyMessage;
					else
						throw new Error();
				} else if (action.indexOf('restore-') === 0)
					refreshingCore = true;
			}).catch(function() {
				actionError = _('Unable to start backup operation');
			}).then(function() {
				starting = false;
				return refresh();
			});
		}

		show(initial);
		poll.add(refresh, 3);
		return E('div', {}, [
			E('link', { 'rel': 'stylesheet', 'href': L.resource('view/adguardhome/compact.css') }),
			sharedStatus.node,
			E('section', { 'class': 'cbi-section agh-compact-card agh-backup-card' }, [
				E('h3', {}, _('Backup history')),
				E('div', { 'class': 'agh-backup-content' }, [
					E('div', { 'class': 'agh-backup-summary' }, [
						E('p', { 'class': 'agh-backup-description' },
							_('Before a core update, the core and YAML configuration are backed up together. The latest 3 automatic backups, 5 manual core backups, and 5 manual YAML backups are kept.')),
						message
					]),
					E('div', { 'class': 'agh-backup-layout' }, [
						E('div', { 'class': 'agh-backup-row agh-backup-toolbar' }, [createCore, createConfig]),
						list
					]),
					empty
				])
			])
		]);
	}
});
