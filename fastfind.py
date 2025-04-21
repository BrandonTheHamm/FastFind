import sublime, sublime_plugin
import os
import subprocess
import threading
import errno
import json
import pickle

#------------------------------------------------------------------------------
FASTFIND_PLUGIN_DIR = os.path.basename(os.path.dirname(os.path.realpath(__file__)))

# Package Control on ST3 compresses the package into a single "package-name.sublime-package" file,
# but ST3 internally treats the location of the package's contents as being in "Packages/packages-name/"
if FASTFIND_PLUGIN_DIR.find(".sublime-package") != -1:
	FASTFIND_PLUGIN_DIR = FASTFIND_PLUGIN_DIR[0:FASTFIND_PLUGIN_DIR.find(".sublime-package")]

FASTFIND_CONTEXT_MENU = os.path.dirname(os.path.realpath(__file__)) + "/Context.sublime-menu"
FASTFIND_SETTINGS_FILE = os.path.dirname(os.path.realpath(__file__)) + "/fastfind.sublime-settings"
FASTFIND_SYNTAX_FILE = "Packages/" + FASTFIND_PLUGIN_DIR + "/FastFindResults.hidden-tmLanguage"

search_history = {}

#------------------------------------------------------------------------------
def get_nth_key(dictionary, n=0):
	if n < 0:
		n += len(dictionary)
	for i, key in enumerate(dictionary.keys()):
		if i == n:
			return key
	raise IndexError("dictionary index out of range")

#------------------------------------------------------------------------------
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
			'"FastFindSublime_before_context":1,\n'
			'"FastFindSublime_after_context":1,\n'
			'"FastFindSublime_display_outline": true,'.format(key))
			sublime.error_message(error_string)

#------------------------------------------------------------------------------
def get_history_save_location() -> str:
	search_history_filename = get_setting("history_file")
	if search_history_filename != None:
		save_dir = os.path.join(sublime.packages_path(), "FastFind")
		project_file_path = sublime.active_window().project_file_name()
		if project_file_path != None:
			# we have a project loaded, so prefer to save in the project folder
			save_dir = os.path.dirname(project_file_path)

		search_history_filename = os.path.join(save_dir, search_history_filename)
		print("history file path: " + search_history_filename)
		return search_history_filename
	return None

#------------------------------------------------------------------------------
def open_file_in_view(filename: str, line_number: int, char_index: int, preview_only: bool) -> sublime.View:
		window = sublime.active_window()
		flags = sublime.ENCODED_POSITION
		if preview_only:
			flags |= sublime.TRANSIENT
		encoded_filename = "{0}:{1}:{2}".format(filename, line_number, char_index)
		view = window.open_file(fname=encoded_filename,group=-1, flags=flags)
		return view

#------------------------------------------------------------------------------
class FastFindResult:
	def __init__(self, filename: str, line_number: int, startpos: int, matchlen: int):
		self.filename = filename
		self.line_number = line_number
		self.start_char_index = startpos
		self.match_length = matchlen

	@staticmethod
	def from_json(json_content):
		start_pos = int(json_content['submatches'][0]['start'])
		match_len = int(json_content['submatches'][0]['end']) - start_pos
		return FastFindResult(json_content['path']['text'],
			int(json_content['line_number']),
			start_pos,
			match_len)

	def to_string(self) -> str:
		return "FastFindResult: filename = {0}\n\tline_number = {1}\n\tstart_char_index = {2}\n\tmatch_length = {3}\n".format(
			self.filename,
			self.line_number,
			self.start_char_index,
			self.match_length)


#------------------------------------------------------------------------------
class FastFindSublimeWorker(threading.Thread):
	def __init__(self, view, platform, root, symbol, folder, executable, case_sensitive):
		super(FastFindSublimeWorker, self).__init__()
		self._view = view
		self._platform = platform
		self._root = root
		self._symbol = symbol
		self._folder = folder
		self._executable = executable
		self._output = []
		self._case_sensitive = case_sensitive

	def make_fastfind_cmd(self, folder, word):
		if folder is None or folder == "":
			sublime.error_message("No search path specified!")
			return ([], [])

		#FIXME(BH): replace with search executable specified in user preferences
		fastfind_arg_list = [str(get_setting("executable"))] #["rg"]
		fastfind_arg_list.append("--json")

		if self._case_sensitive == False:
			fastfind_arg_list.append("-i")

		fastfind_arg_list.append("-B"+str(get_setting("before_context")))
		fastfind_arg_list.append("-A"+str(get_setting("after_context")))

		std_file_types = get_setting("file_type_pattern")
		if std_file_types is not None:
			for file_type in std_file_types:
				fastfind_arg_list.append("-t"+file_type)

		non_std_file_types = get_setting("non_std_file_type_pattern")
		if non_std_file_types is not None:
			for file_type in non_std_file_types:
				fastfind_arg_list.append("--type-add")
				fastfind_arg_list.append("%s:*.%s" % (file_type, file_type))
			for file_type in non_std_file_types:
				fastfind_arg_list.append("-t"+file_type)

		path = folder
		print("FastFind: Search path is '{0}'".format(path))

		fastfind_arg_list.append("--column")
		fastfind_arg_list.append(word)
		fastfind_arg_list.append(path)

		# print("FastFind: make_fastfind_cmd: fastfind_arg_list = {0}".format(fastfind_arg_list))
		popen_arg_list = {
			"shell": False,
			"stdout": subprocess.PIPE,
			"stderr": subprocess.PIPE,
			"cwd": self._root
		}

		if self._platform == "windows":
			popen_arg_list["creationflags"] = 0x08000000

		return fastfind_arg_list, popen_arg_list

	def run_fastfind(self, folder: str, word: str) -> str:
		fastfind_arg_list, popen_arg_list = self.make_fastfind_cmd(folder, word)
		try:
			proc = subprocess.Popen(fastfind_arg_list, **popen_arg_list)
		except OSError as e:
			if e.errno == errno.ENOENT:
				sublime.error_message("FastFind ERROR: fastfind binary \"%s\" not found!" % self._executable)
			else:
				sublime.error_message("FastFind ERROR: %s failed!" % fastfind_arg_list)
			print("FastFind: Exiting due to error")
			return ""

		output, erroroutput = proc.communicate()

		# if erroroutput is not None and erroroutput.strip() != "":
		# 	print("FastFind: erroroutput = '{0}'".format(erroroutput))

		try:
			output = str(output, encoding="utf8")
		except TypeError:
			output = unicode(str(output), encoding="utf8")

		# print("FastFind: output = {0}".format(output))
		return output

	def process_results(self, results):
		for line in results:
			print(line)

	def run(self) -> None:
		print("[FastFind] Searching '%s' for '%s'" % (self._folder, self._symbol))
		results = self.run_fastfind(self._folder, self._symbol)
		search_result_locations = parse_search_results_from_json(results)
		self._output = search_result_locations

#------------------------------------------------------------------------------
def parse_search_results_from_json(content: str) -> list:
	results = []
	# NOTE(BH): Ripgrep splits json results using Unix line-endings, so even on Windows,
	# we need split the results on the Unix line termination character and not use os.linesep
	for line in content.split("\n"):
		# print("\n\nline:\n\n{0}\n\n".format(line))
		line = line.strip()
		if line == "":
			# print("blank line...skipping")
			continue
		json_result = json.loads(line)
		# print("json_result: ", json_result)

		if json_result['type'] == 'match':
			# print("found match type")
			find_result = FastFindResult.from_json(json_result['data'])
			if find_result != None:
				# print(find_result.to_string())
				results.append(find_result)
	return results


#------------------------------------------------------------------------------
class ShowSearchHistoryHandler(sublime_plugin.TextInputHandler):
	def placeholder(self):
		return 

#------------------------------------------------------------------------------
class SearchTermInputHandler(sublime_plugin.TextInputHandler):
	def placeholder(self):
		return "Search Term"

	def initial_text(self):
		if sublime.active_window() is not None:
			if sublime.active_window().active_view() is not None:
				view = sublime.active_window().active_view()
				first_sel = view.sel()[0]
				left = first_sel.a
				right = first_sel.b
				view.sel().add(sublime.Region(left, right))

				search_term = ""

				if left == right:
					search_term = view.substr(view.word(left))
				else:
					search_term = view.substr(first_sel)
				return search_term
		return ""

	def description(self, text):
		return "Enter a search term"



#------------------------------------------------------------------------------
class FolderInputHandler(sublime_plugin.TextInputHandler):
	def placeholder(self):
		return "Search Path"

	def initial_text(self):
		# Prefer to use the current project directory as the search path 
		if sublime.active_window().project_file_name() is not None:
			proj_file = sublime.active_window().project_file_name()
			print("FastFind: Loaded Project File: ",proj_file)
			folder_path = os.path.dirname(os.path.realpath(proj_file))
			return folder_path
		elif len(sublime.active_window().folders()) > 0:
			# if no project is open, but folders are open, then use the first folder path as the 
			# search path
			folder_path = sublime.active_window().folders()[0]
			print("FastFind: Loaded folder_path: ",folder_path)
			return folder_path
		else:
			view = sublime.active_window().active_view()
			if view is not None:
				filename = view.buffer().file_name()
				if filename is not None:
					folder_path = os.path.dirname(os.path.realpath(filename))
					print("FastFind: Path of currently open file: ",folder_path)
					return folder_path
		return "enter a search path"


	def description(self, text):
		return "FastFind Search Path"



#------------------------------------------------------------------------------
class FastFindCommand(sublime_plugin.TextCommand):
	def __init__(self, view: sublime.View):
		self.view = view
		if view is None:
			print("[FastFind] No view opened - using active window instead")
			self.view = sublime.active_window().view()
			if self.view is None:
				print("[FastFind] WHAT? Still no view???")

		self._executable = None
		self._root = None
		self._find_results = []
		self._current_position = None
		self._saved_viewport_pos = None
		self._folder = None
		print("[FastFind] Loaded")


	def __del__(self):
		print("[FastFind] Unloading")

	def save_history_to_file(self):
		global search_history
		filename = get_history_save_location()
		if filename != None:
			with open(filename, "wb+") as history_file:
				pickle.dump(search_history, history_file)


	def _update_status(self, workers: list, msgStr: str, show_results: bool, count: int = 0, dir: int = 1) -> None:
		count = count + dir
		found = False

		for worker in workers:
			if worker.is_alive():
				found = True
				if count == 7:
					dir = -1
				elif count == 0:
					dir = 1
				sublime.set_timeout(lambda: self._update_status(workers, msgStr, show_results, count, dir), 100)
				break

		if not found:
			self.view.erase_status("FastFindSublime")
			output = ""
			if show_results:
				for worker in workers:
					for result in worker._output:
						self._find_results.append(result)
					search_history[worker._symbol] = worker._output
					self.save_history_to_file()
					self._display_results_in_jump_list(worker._symbol, worker._output)


	def _select_entry(self, index: int) -> None:
		# print("_select_entry called with index = {0}".format(index))
		if index < 0:
			# print("FastFind: cancelled navigation - return to previous position")
			# cancelled, return to saved position
			if self.view is None:
				self.view = sublime.active_window().view()
				if self.view is None:
					print("[FastFind] view is still none!!")

			if self.view.window() is None:
				sublime.active_window().focus_view(self.view)
			else:
				self.view.window().focus_view(self.view)

			self.view.sel().clear()
			self.view.sel().add(self._current_position)
			self.view.set_viewport_position(self._saved_viewport_pos, animate=True)
		else:
			# print("skipping...for index = {0}".format(index))
			selected_entry = self._find_results[index]
			# print("_select_entry %d: %s:%d:%d" % (index, selected_entry.filename, selected_entry.line_number, selected_entry.start_char_index))
			view = open_file_in_view(selected_entry.filename,
				selected_entry.line_number,
				selected_entry.start_char_index+1,
				False)
			sublime.active_window().focus_view(view)
		

	def _highlight_entry(self, index: int) -> None:
		# print("_highlight_entry called with index = {0}".format(index))
		highlighted_result = self._find_results[index]
		# print("_highlight_entry %d : %s:%d:%d" % (index, highlighted_result.filename, highlighted_result.line_number, highlighted_result.start_char_index))
		preview = open_file_in_view(highlighted_result.filename, 
			highlighted_result.line_number,
			highlighted_result.start_char_index,
			True)
		result_location = preview.text_point(highlighted_result.line_number-1, highlighted_result.start_char_index)
		result_region = sublime.Region(result_location, result_location+highlighted_result.match_length)
		preview.sel().add(result_region)


	def _display_results_in_jump_list(self, symbol: str, locations: list):
		self._find_results = locations
		window = self.view.window()

		items = []
		for location in locations:
			items.append(sublime.QuickPanelItem(
				"{0}:{1}".format(os.path.basename(location.filename), location.line_number)))

		# print("_display_results: num items = {0}".format(len(items)))
		window.show_quick_panel(items=items,
			on_select=self._select_entry,
			on_highlight=self._highlight_entry, 
			flags=sublime.KEEP_OPEN_ON_FOCUS_LOST, 
			placeholder="[FastFind] found {0} occurrences of '{1}'".format(len(items), symbol))


	def _open_basic_file(self, 
		filename: str, 
		line_number: int, 
		char_index: int, 
		preview_only: bool) -> sublime.View:
		window = sublime.active_window()
		flags = sublime.ENCODED_POSITION
		if preview_only:
			flags |= sublime.TRANSIENT
		encoded_filename = "{0}:{1}:{2}".format(filename, line_number, char_index)
		view = window.open_file(fname=encoded_filename,group=-1, flags=flags)
		return view


	def _on_search_confirmed(self, symbol):
		print("[FastFind] Searching for symbol '%s' in path '%s'" % (symbol, self._folder))
		worker = FastFindSublimeWorker(
				view = self.view,
				platform = sublime.platform(),
				root = self._root,
				symbol = symbol,
				folder = self._folder,
				executable = self._executable,
				case_sensitive = self._case_sensitive)
		worker.start()
		self.workers.append(worker)
		self._update_status(self.workers, symbol, True)


	def input(self, args):
		if "search_term" not in args:
			return SearchTermInputHandler()

		if "folder" not in args:
			return FolderInputHandler()


	def run(self, _, case_sensitive, folder, search_term):
		self._case_sensitive = case_sensitive
		self._folder = os.path.expandvars(folder)
		# print("FastFind search path: ",self._folder)
		# print("FastFind search term: ",search_term)
		# print("FastFind case_sensitive: ",case_sensitive)

		if self.view is not None:
			self._current_position = self.view.sel()[0]
			self._saved_viewport_pos = self.view.viewport_position()
		else:
			self._current_position = None
			self._saved_viewport_pos = None

		self._executable = get_setting("executable")

		self.workers = []
		self._on_search_confirmed(search_term)


class FastFindShowHistoryCommand(sublime_plugin.TextCommand):
	def __init__(self, view):
		self.view = view
		self.load_history_from_file()			

	def load_history_from_file(self):
		global search_history
		filename = get_history_save_location()
		if filename != None:
			if os.path.isfile(filename):
				with open(filename, "rb") as history_file:
					search_history = pickle.load(history_file)

	def run(self, _):
		if self.view is not None:
			self._current_position = self.view.sel()[0]
			self._saved_viewport_pos = self.view.viewport_position()
		else:
			self._current_position = None
			self._saved_viewport_pos = None
		self.show_search_history_in_jumplist()


	def _log(self, msg):
		print("[FastFindShowHistory] %s" % (msg))


	def show_search_history_in_jumplist(self):
		window = self.view.window()
		items = []
		# self._log(search_history)
		for search_term, search_results in search_history.items():
			self._log("Search term = " + search_term)
			items.append(sublime.QuickPanelItem(search_term,
				annotation="{0} results".format(len(search_results))))

		window.show_quick_panel(
			items=items,
			on_select=self._select_search_history_entry,
			placeholder="FastFind Search History - {0} items".format(len(items)))


	def _select_search_history_entry(self, index: int) -> None:
		if index >= 0:
			search_term = get_nth_key(search_history, index)
			selected_entry = search_history[search_term]
			self._display_results_in_jump_list(search_term, selected_entry)


	def _select_entry(self, index: int) -> None:
		if index < 0:
			# cancelled, return to saved position
			if self.view is None:
				self.view = sublime.active_window().view()
				if self.view is None:
					print("[FastFindShowHistory] view is still none!!")

			if self.view.window() is None:
				sublime.active_window().focus_view(self.view)
			else:
				self.view.window().focus_view(self.view)

			self.view.sel().clear()
			self.view.sel().add(self._current_position)
			self.view.set_viewport_position(self._saved_viewport_pos, animate=True)
		else:
			selected_entry = self._find_results[index]
			# print("_select_entry %d: %s:%d:%d" % (index, selected_entry.filename, selected_entry.line_number, selected_entry.start_char_index))
			view = open_file_in_view(selected_entry.filename,
				selected_entry.line_number,
				selected_entry.start_char_index+1,
				False)
			sublime.active_window().focus_view(view)


	def _highlight_entry(self, index: int) -> None:
		# print("_highlight_entry called with index = {0}".format(index))
		highlighted_result = self._find_results[index]
		# print("_highlight_entry %d : %s:%d:%d" % (index, highlighted_result.filename, highlighted_result.line_number, highlighted_result.start_char_index))
		preview = open_file_in_view(highlighted_result.filename, 
			highlighted_result.line_number,
			highlighted_result.start_char_index,
			True)
		result_location = preview.text_point(highlighted_result.line_number-1, highlighted_result.start_char_index)
		result_region = sublime.Region(result_location, result_location+highlighted_result.match_length)
		preview.sel().add(result_region)


	def _display_results_in_jump_list(self, symbol: str, locations: list):
		self._find_results = locations
		window = self.view.window()

		items = []
		for location in locations:
			items.append(sublime.QuickPanelItem(
				"{0}:{1}".format(os.path.basename(location.filename), location.line_number)))

		# print("_display_results: num items = {0}".format(len(items)))
		window.show_quick_panel(items=items,
			on_select=self._select_entry,
			on_highlight=self._highlight_entry, 
			flags=sublime.KEEP_OPEN_ON_FOCUS_LOST, 
			placeholder="FastFind found {0} occurrences of '{1}'".format(len(items), symbol))