import sublime, sublime_plugin
import os
import subprocess
import string
import threading
import errno

FASTFIND_PLUGIN_DIR = os.path.basename(os.path.dirname(os.path.realpath(__file__)))

# Package Control on ST3 compresses the package into a single "package-name.sublime-package" file,
# but ST3 internally treats the location of the package's contents as being in "Packages/packages-name/"
if FASTFIND_PLUGIN_DIR.find(".sublime-package") != -1:
	FASTFIND_PLUGIN_DIR = FASTFIND_PLUGIN_DIR[0:FASTFIND_PLUGIN_DIR.find(".sublime-package")]

FASTFIND_CONTEXT_MENU = os.path.dirname(os.path.realpath(__file__)) + "/Context.sublime-menu"
FASTFIND_SETTINGS_FILE = os.path.dirname(os.path.realpath(__file__)) + "/fastfind.sublime-settings"
FASTFIND_SYNTAX_FILE = "Packages/" + FASTFIND_PLUGIN_DIR + "/FastFindResults.hidden-tmLanguage"

def getPlatformNewline():
	if sublime.platform == "windows":
		return '\r\n'
	else:
		return '\n'

def get_setting(key, default=None, view=None):
		s = sublime.load_settings("fastfind.sublime-settings")
		if view == None:
			view = sublime.active_window().active_view()
		if s.has("FastFindSublime_%s" % key):
			return s.get("FastFindSublime_%s" % key)
		else:
			error_string = ('\"{0}\" settting not specified\n'
			'Add the following to your user FastFind.sublime-setttings:\n\n'
			'"FastFindSublime_file_type_pattern":\n'
			'["c", "h", "sh", "make"],\n'
			'"FastFindSublime_non_std_file_type_pattern":\n'
			'["x", "s", "scons", "api","],\n'
			'"FastFindSublime_ignore_folders": [],\n'
			'"FastFindSublime_prompt_before_searching": false,\n'
			'"FastFindSublime_executable": "rg",\n'
			'"FastFindSublime_executable": "rg",\n'
			'"FastFindSublime_before_context":1,\n'
			'"FastFindSublime_after_context":1,\n'
			'"FastFindSublime_display_outline": true,'.format(key))
			sublime.error_message(error_string)


class FastFindVisitor(sublime_plugin.TextCommand):
	def __init__(self, view):
		self.view = view

	# def run(self, edit):
	def run_(self, view, args):
		for region in self.view.sel():
			# Find anything looking like file in whole line at cursor
			if not region.empty():
				break
			match_line = self.view.substr(self.view.line(region))
			lineDetails = match_line.split(":")
			if lineDetails:
				if len(lineDetails) >= 4:
					filePath = lineDetails[0] + ":" + lineDetails[1]
					fileRowCol = lineDetails[2] + ":" + lineDetails[3]
					if(os.path.isfile(filePath)):
						sublime.active_window().open_file(filePath + ":" + fileRowCol, sublime.ENCODED_POSITION)
					# else:
						# sublime.error_message("Unable to open file")


def getEncodedPosition(file_name, line_num):
	return file_name + ":" + str(line_num)


def getCurrentPosition(view):
	if view.file_name():
		return getEncodedPosition( view.file_name(), view.rowcol( view.sel()[0].a )[0] + 1 )
	else:
		return None


class FastFindSublimeWorker(threading.Thread):
	def __init__(self, view, platform, root, symbol, folder, executable):
		super(FastFindSublimeWorker, self).__init__()
		self.view = view
		self.platform = platform
		self.root = root
		self.symbol = symbol
		self.folder = folder
		self.executable = executable

	def make_fastfind_cmd(self, folder, word):
		newline = getPlatformNewline()
		before_context = get_setting("before_context")
		after_context = get_setting("after_context")
		std_file_types = get_setting("file_type_pattern")
		non_std_file_types = get_setting("non_std_file_type_pattern")
		added_file_types = non_std_file_types
		std_file_types = " ".join(['-t%s' % s for s in std_file_types])
		non_std_file_types = " ".join(['--type-add "%s:*.%s"' % (s,s) for s in non_std_file_types])
		added_file_types = " ".join(['-t%s' % s for s in added_file_types])
		if not folder == "":
			path = os.path.join(os.path.dirname(self.view.window().project_file_name()), folder)
		context_before_text = "-B" + str(before_context)
		context_after_text = "-A" + str(after_context)
		fastfind_arg_list = " ".join([self.executable, context_before_text, context_after_text, non_std_file_types, std_file_types, added_file_types, "--column", word, path])

		print(fastfind_arg_list)
		popen_arg_list = {
			"shell": False,
			"stdout": subprocess.PIPE,
			"stderr": subprocess.PIPE,
			"cwd": self.root
		}
		if (self.platform == "windows"):
			popen_arg_list["creationflags"] = 0x08000000
		# print(popen_arg_list)
		return fastfind_arg_list, popen_arg_list


	def run_fastfind(self, folder, word):
		fastfind_arg_list, popen_arg_list = self.make_fastfind_cmd(folder, word)
		try:
			proc = subprocess.Popen(fastfind_arg_list, **popen_arg_list)
		except OSError as e:
			if e.errno == errno.ENOENT:
				sublime.error_message("FastFind ERROR: fastfind binary \"%s\" not found!" % self.executable)
			else:
				sublime.error_message("FastFind ERROR: %s failed!" % fastfind_arg_list)

		output, erroroutput = proc.communicate()

		# print erroroutput
		try:
			output = str(output, encoding="utf8")
		except TypeError:
			output = unicode(str(output), encoding="utf8")
		# print(output)
		return output

	def process_results(self, results):
		for line in results:
			print(line)


	def run(self):
			results = self.run_fastfind(self.folder, self.symbol)
			# process_results(results)
			self.output = results


class FastFindCommand(sublime_plugin.TextCommand):
	fastfind_output_info  = {}

	def __init__(self, view):
		self.view = view
		self.database = None
		self.executable = None
		self.root = None


	def update_status(self, workers, msgStr, showResults, count=0, dir=1):
		count = count + dir
		found = False

		for worker in workers:
			if worker.is_alive():
				found = True
				if count == 7:
					dir = -1
				elif count == 0:
					dir = 1
				sublime.status_message("FastFinding '%s' [%s=%s]" %	(msgStr, ' ' * count, ' ' * (7 - count)))
				sublime.set_timeout(lambda: self.update_status(workers, msgStr, showResults, count, dir), 100)
				break

		if not found:
			self.view.erase_status("FastFindSublime")
			output = ""
			if showResults:
				for worker in workers:
					self.display_results(worker.symbol, worker.output)


	def display_results(self, symbol, output):
		before_context = get_setting("before_context")
		after_context = get_setting("after_context")
		FastFind_view = self.view.window().new_file()
		FastFind_view.set_scratch(True)
		FastFind_view.set_name("FastFind results - " + symbol + " " + self.folder)
		FastFindCommand.fastfind_output_info['view'] = FastFind_view
		FastFindCommand.fastfind_output_info['pos'] = 0
		FastFindCommand.fastfind_output_info['text'] = "%s in %s\n\n%s" %  (symbol, self.folder, output)
		FastFindCommand.fastfind_output_info['symbol'] = symbol
		FastFind_view.run_command("display_fast_find_results")
		FastFind_view.set_syntax_file(FASTFIND_SYNTAX_FILE)
		FastFind_view.set_read_only(True)

	def run(self, edit, folder):
		self.folder = folder
		self.executable = get_setting("executable")
		if (self.folder == ""):
			openViews = self.view.window().views()
			for view in openViews:
				if view.is_scratch():
					if "FastFind results - " in view.name():
						#found a FastFind tab, close it
						self.view.window().focus_view(view)
						self.view.window().run_command("close_file")
			return
		if (self.folder == "__new__"):
			fast_find_menu = os.path.join(FASTFIND_CONTEXT_MENU)
			if os.path.exists(fast_find_menu):
				self.view.window().open_file(fast_find_menu)
			else:
				sublime.error_message("Context.sublime-menu not found at\n%s" % fast_find_menu)
			return
		if(self.folder == "__settings__"):
			fast_find_settings = os.path.join(FASTFIND_SETTINGS_FILE)
			if os.path.exists(fast_find_settings):
				self.view.window().open_file(fast_find_settings)
			else:
				sublime.error_message("fastfind.sublime-settings not found at\n%s" % fast_find_settings)
			return
		if not self.view.file_name():
			sublime.error_message("No sublime project is open")
			return

		if not self.view.window().project_file_name() != None:
			sublime.error_message("No sublime project is open")
			return

		cur_pos = getCurrentPosition(self.view)

		# Search for the first word that is selected. While Sublime Text uses
		# multiple selections, we only want the first selection since simultaneous
		# multiple fastfind lookups are not supported
		first_selection = self.view.sel()[0]
		one = first_selection.a
		two = first_selection.b

		self.view.sel().add(sublime.Region(one, two))
		self.workers = []

		if one == two: #nothing selected, cursor is just at a word, so select full word
			symbol = self.view.substr(self.view.word(one))
		else: #soemthing is selected, so use the selection
			symbol = self.view.substr(first_selection)
		if get_setting("prompt_before_searching") == True:
			print("Not supported yet")
		else:
			self.on_search_confirmed(symbol)

	def on_search_confirmed(self, symbol):
		worker = FastFindSublimeWorker(
				view = self.view,
				platform = sublime.platform(),
				root = self.root,
				symbol = symbol,
				folder = self.folder,
				executable = self.executable
			)
		worker.start()
		self.workers.append(worker)
		self.update_status(self.workers, symbol, True)


class DisplayFastFindResultsCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		last_pos = self.view.insert(edit, FastFindCommand.fastfind_output_info['pos'], FastFindCommand.fastfind_output_info['text'])
		symbol_regions = self.view.find_all(FastFindCommand.fastfind_output_info['symbol'], sublime.LITERAL)
		if get_setting("display_outline"):
			self.view.add_regions('FastFindsublime-outlines', symbol_regions[1:], "text.find-in-files", "dot", sublime.DRAW_EMPTY_AS_OVERWRITE)
		else:
			self.view.add_regions('FastFindsublime-outlines', symbol_regions[1:], "text.find-in-files", "dot", sublime.HIDDEN)
		self.view.insert(edit, 0, "Found %s hit(s) for " % len(self.view.get_regions('FastFindsublime-outlines')))
