import { register } from './i18n.svelte'

// Words both apps use.
register(
  {
    'date.today': 'Today', 'date.yesterday': 'Yesterday', 'date.today_at': 'today {time}',
    'msg.edited': 'edited', 'msg.edit': 'Edit', 'msg.delete': 'Delete', 'msg.really_delete': 'Really delete?',
    'msg.edit_label': 'Edit message', 'msg.save': 'Save', 'msg.cancel': 'Cancel',
    'composer.message': 'Message', 'composer.send': 'Send', 'composer.attach': 'Attach a file', 'composer.remove_file': 'Remove file',
    'channel.members': 'Members', 'channel.only_people': 'Only people write here',
  },
  {
    'date.today': 'Heute', 'date.yesterday': 'Gestern', 'date.today_at': 'heute {time}',
    'msg.edited': 'bearbeitet', 'msg.edit': 'Bearbeiten', 'msg.delete': 'Löschen', 'msg.really_delete': 'Wirklich löschen?',
    'msg.edit_label': 'Nachricht bearbeiten', 'msg.save': 'Speichern', 'msg.cancel': 'Abbrechen',
    'composer.message': 'Nachricht', 'composer.send': 'Senden', 'composer.attach': 'Datei anhängen', 'composer.remove_file': 'Datei entfernen',
    'channel.members': 'Mitglieder', 'channel.only_people': 'Hier schreiben nur Menschen',
  },
)
