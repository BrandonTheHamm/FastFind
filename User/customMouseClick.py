import sublime, sublime_plugin

class CustomMouseclickCommand(sublime_plugin.TextCommand):
	def run_(self, view, args):
		if self.view.name().startswith("FastFind results"):
			self.view.run_command("fast_find_visitor")
			return
		self.view.run_command('expand_selection', {'to': 'word'})
